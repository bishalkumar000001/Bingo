from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from database import get_leaderboard_filtered
from html import escape

SCOPE_ICONS = {"global": "🌐 Global", "chat": "📍 Current Chat"}
TIME_ICONS = {
    "today": "🟡 Today",
    "week": "🟡 Week",
    "month": "🔵 Month",
    "year": "🟣 Year",
    "all_time": "🏆 All Time",
}


def build_leaderboard_keyboard(scope: str, time_filter: str, chat_id: int) -> InlineKeyboardMarkup:
    def _btn(s: str, t: str, label: str) -> InlineKeyboardButton:
        active = s == scope and t == time_filter
        return InlineKeyboardButton(
            label + (" ✅" if active else ""),
            callback_data=f"lb:{s}:{t}:{chat_id}",
        )

    if chat_id:
        chat_btn = _btn("chat", time_filter, "📍 Current Chat")
    else:
        chat_btn = InlineKeyboardButton("📍 Current Chat", callback_data="lb_nochat")

    return InlineKeyboardMarkup([
        [chat_btn, _btn("global", time_filter, "🌐 Global")],
        [
            _btn(scope, "today", "🟡 Today"),
            _btn(scope, "week", "🟡 Week"),
            _btn(scope, "month", "🔵 Month"),
        ],
        [
            _btn(scope, "year", "🟣 Year"),
            _btn(scope, "all_time", "🏆 All Time"),
        ],
    ])


def _display_name(row: dict) -> str:
    # Prefer the real Telegram @username when it is available.
    username = row.get("username")
    if username:
        name = "@" + str(username).lstrip("@")
    else:
        name = row.get("first_name") or str(row.get("telegram_id", "Player"))
    return str(name)


def _name(row: dict) -> str:
    user_id = row.get("telegram_id")
    display_name = _display_name(row)
    MAX_NAME_LENGTH = 15
    if len(display_name) > MAX_NAME_LENGTH:
        display_name = display_name[:MAX_NAME_LENGTH] + "…"
    return f'<a href="tg://user?id={user_id}">{escape(display_name)}</a>'


def _font(size: int, bold: bool = False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit_name(name: str, max_chars: int = 18) -> str:
    return name if len(name) <= max_chars else name[:max_chars - 1] + "…"


async def build_leaderboard_image(
    scope: str = "global",
    time_filter: str = "all_time",
    chat_id: int = 0,
    chat_title: str = "",
) -> BytesIO:
    """Create a live Top-10 leaderboard card in the red/black bar-chart style."""
    rows = await get_leaderboard_filtered(scope, chat_id, time_filter, limit=10)

    width, height = 1200, 860
    image = Image.new("RGB", (width, height), "#eeeeee")
    draw = ImageDraw.Draw(image)

    # Main rounded card mask/background.
    card = (55, 25, width - 55, height - 25)
    draw.rounded_rectangle(card, radius=70, fill="#130001")

    # Decorative red arcs, matching the reference style.
    arc_width = 58
    draw.arc((45, -120, 330, 165), 20, 165, fill="#a40020", width=arc_width)
    draw.arc((900, -135, 1175, 145), 15, 170, fill="#a40020", width=arc_width)
    draw.arc((-105, 300, 135, 610), 250, 95, fill="#8d001b", width=arc_width)
    draw.arc((1000, 420, 1280, 700), 75, 255, fill="#8d001b", width=arc_width)
    draw.arc((55, 770, 350, 1035), 195, 350, fill="#6f0015", width=arc_width)

    title_font = _font(70, True)
    name_font = _font(24, True)
    user_font = _font(18, False)
    coin_font = _font(23, True)
    rank_font = _font(25, True)
    footer_font = _font(20, False)

    # Header.
    draw.text((width // 2, 86), "LEADERBOARD", font=title_font, anchor="mm", fill="#f4f4f4")
    draw.text((width // 2, 150), "TOP 10 PLAYERS", font=_font(22, True), anchor="mm", fill="#c9a0a8")

    # Inner leaderboard panel.
    panel = (105, 180, width - 105, 740)
    draw.rounded_rectangle(panel, radius=28, fill="#210002", outline="#a52a3a", width=3)

    if not rows:
        draw.text((width // 2, 460), "No leaderboard scores yet", font=_font(36, True), anchor="mm", fill="#f4f4f4")
    else:
        max_coins = max(max(int(r.get("coins", 0) or 0) for r in rows), 1)
        medals = ["1", "2", "3"]
        y = 208
        row_h = 49
        row_gap = 6
        bar_x = 390
        max_bar_width = 610

        for rank, row in enumerate(rows[:10], start=1):
            coins = int(row.get("coins", 0) or 0)

            # Rank badge.
            badge_fill = "#b67600" if rank == 1 else ("#777777" if rank == 2 else ("#914817" if rank == 3 else "#3a0b12"))
            draw.ellipse((135, y + 3, 180, y + 48), fill=badge_fill, outline="#d7d7d7" if rank <= 3 else "#6f2430", width=2)
            draw.text((157, y + 25), str(rank), font=rank_font, anchor="mm", fill="#ffffff")

            # Simple circular avatar with the player's initial. This keeps the card
            # dynamic without requiring Telegram profile-photo downloads.
            first_name = str(row.get("first_name") or "Player")
            initial = first_name[:1].upper() if first_name else "P"
            draw.ellipse((195, y + 3, 240, y + 48), fill="#420912", outline="#b54252", width=2)
            draw.text((217, y + 25), initial, font=_font(22, True), anchor="mm", fill="#ffffff")

            display = first_name if row.get("first_name") else _display_name(row)
            display = _fit_name(display, 16)
            username = row.get("username")
            handle = "@" + str(username).lstrip("@") if username else ""
            handle = _fit_name(handle, 17)

            draw.text((255, y + 10), display, font=name_font, fill="#f1eef0")
            if handle:
                draw.text((255, y + 34), handle, font=user_font, fill="#c18b94")

            # Bar background and value bar.
            draw.rounded_rectangle((bar_x, y + 4, bar_x + max_bar_width, y + 48), radius=8, fill="#34070d")
            bar_width = max(72, int(max_bar_width * coins / max_coins))
            bar_end = bar_x + min(max_bar_width, bar_width)
            draw.rounded_rectangle((bar_x, y + 4, bar_end, y + 48), radius=8, fill="#df3657")

            # Coin value on/at the end of the bar.
            value_x = bar_end - 16 if bar_width >= 145 else bar_end + 14
            anchor = "rm" if bar_width >= 145 else "lm"
            draw.text((value_x, y + 26), f"${coins:,}", font=coin_font, anchor=anchor, fill="#ffffff")

            y += row_h + row_gap

    # Footer line and text.
    draw.line((210, 775, width - 210, 775), fill="#8f2435", width=2)
    scope_text = chat_title if scope == "chat" and chat_title else ("GLOBAL" if scope == "global" else "CURRENT CHAT")
    draw.text((width // 2, 810), f"{scope_text}  •  KEEP PLAYING AND CLIMB THE RANKINGS!", font=footer_font, anchor="mm", fill="#d0a2aa")

    output = BytesIO()
    output.name = "velocity_bingo_top10.png"
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output

async def build_leaderboard_text(
    scope: str = "global",
    time_filter: str = "all_time",
    chat_id: int = 0,
    chat_title: str = "",
) -> str:
    rows = await get_leaderboard_filtered(scope, chat_id, time_filter)

    scope_label = SCOPE_ICONS[scope]
    time_label = TIME_ICONS[time_filter]

    if scope == "chat" and chat_title:
        scope_label = f"📍 {chat_title}"

    header = (
        "<blockquote>"
        f" <b>Bingo — Leaderboard</b> \n"
        f"{scope_label} | {time_label}"
        "</blockquote>"
    )

    if not rows:
        period_map = {
            "today": "today",
            "week": "this week",
            "month": "this month",
            "year": "this year",
            "all_time": "yet",
        }
        period_str = period_map.get(time_filter, "yet")
        where = "in this chat" if scope == "chat" else "globally"
        return header + f"\n📭 No scores recorded {where} {period_str}."

    lines = [
        header,
        "<blockquote>",
    ]
    
    for rank, row in enumerate(rows, start=1):
        name = _name(row)
        coins = row.get("coins", 0)
        
        if rank == 1:
            lines.append(f"🥇 <b>{name}</b> <b>{coins:,}</b>")
        elif rank == 2:
            lines.append(f"🥈 <b>{name}</b> <b>{coins:,}</b>")
        elif rank == 3:
            lines.append(f"🥉 <b>{name}</b> <b>{coins:,}</b>")
        else:
            lines.append(f"{rank}. <b>{name}</b> <b>{coins:,}</b>")
    
    lines.append("</blockquote>")
    return "\n".join(lines)
