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
    """Create a clean neon-style Top-10 leaderboard using usernames only."""
    rows = await get_leaderboard_filtered(scope, chat_id, time_filter, limit=10)

    width, height = 1200, 900
    image = Image.new("RGB", (width, height), "#080a18")
    draw = ImageDraw.Draw(image)

    # Premium dark navy card with a different neon theme.
    outer = (38, 30, width - 38, height - 30)
    draw.rounded_rectangle(outer, radius=48, fill="#0e1126", outline="#2d3566", width=3)

    # Decorative neon shapes.
    draw.ellipse((-180, -180, 220, 220), outline="#4b2cff", width=42)
    draw.ellipse((970, -150, 1370, 250), outline="#00b8ff", width=42)
    draw.ellipse((-120, 680, 260, 1060), outline="#162b72", width=34)
    draw.ellipse((980, 650, 1370, 1040), outline="#5422b8", width=34)

    title_font = _font(72, True)
    sub_font = _font(22, True)
    username_font = _font(25, True)
    coin_font = _font(24, True)
    rank_font = _font(26, True)
    footer_font = _font(18, False)

    # Header.
    draw.text((width // 2, 92), "LEADERBOARD", font=title_font, anchor="mm", fill="#f5f7ff")
    draw.text((width // 2, 145), "TOP 10 PLAYERS • LIVE RANKINGS", font=sub_font, anchor="mm", fill="#8fa5ff")

    # Header accent line.
    draw.rounded_rectangle((410, 174, 790, 180), radius=3, fill="#5b7cff")

    panel = (90, 205, width - 90, 770)
    draw.rounded_rectangle(panel, radius=28, fill="#111633", outline="#303b74", width=2)

    if not rows:
        draw.text((width // 2, 490), "No leaderboard scores yet", font=_font(36, True), anchor="mm", fill="#f5f7ff")
    else:
        max_coins = max(max(int(r.get("coins", 0) or 0) for r in rows), 1)
        y = 228
        row_h = 48
        row_gap = 7
        username_x = 205
        bar_x = 430
        max_bar_width = 590

        for rank, row in enumerate(rows[:10], start=1):
            coins = int(row.get("coins", 0) or 0)

            # Row background.
            draw.rounded_rectangle((115, y, width - 115, y + row_h), radius=12, fill="#171d3d")

            # Rank badge.
            if rank == 1:
                badge_fill, badge_outline = "#f5b942", "#ffe49b"
            elif rank == 2:
                badge_fill, badge_outline = "#aeb9c9", "#edf3ff"
            elif rank == 3:
                badge_fill, badge_outline = "#b46b3e", "#ffd0ae"
            else:
                badge_fill, badge_outline = "#252d55", "#4a568b"

            draw.ellipse((135, y + 4, 175, y + 44), fill=badge_fill, outline=badge_outline, width=2)
            draw.text((155, y + 24), str(rank), font=rank_font, anchor="mm", fill="#101426" if rank <= 3 else "#eaf0ff")

            # Username only — never display first/real name in the image.
            raw_username = row.get("username")
            if raw_username:
                username = "@" + str(raw_username).lstrip("@")
            else:
                username = f"@player_{row.get('telegram_id', rank)}"
            username = _fit_name(username, 20)
            draw.text((username_x, y + 24), username, font=username_font, anchor="lm", fill="#f3f6ff")

            # Bar track.
            draw.rounded_rectangle((bar_x, y + 7, bar_x + max_bar_width, y + 41), radius=9, fill="#0b0f24")

            # Dynamic bar. The leader fills the full available width.
            bar_width = max(64, int(max_bar_width * coins / max_coins))
            bar_end = min(bar_x + max_bar_width, bar_x + bar_width)
            draw.rounded_rectangle((bar_x, y + 7, bar_end, y + 41), radius=9, fill="#5169ff")

            # Coin value is always readable.
            if bar_width >= 170:
                draw.text((bar_end - 16, y + 24), f"${coins:,}", font=coin_font, anchor="rm", fill="#ffffff")
            else:
                draw.text((bar_end + 14, y + 24), f"${coins:,}", font=coin_font, anchor="lm", fill="#dce3ff")

            y += row_h + row_gap

    # Footer.
    draw.line((210, 800, width - 210, 800), fill="#303b74", width=2)
    scope_text = chat_title if scope == "chat" and chat_title else ("GLOBAL" if scope == "global" else "CURRENT CHAT")
    draw.text((width // 2, 842), f"{scope_text}  •  KEEP PLAYING. KEEP CLIMBING.", font=footer_font, anchor="mm", fill="#9eabdc")

    output = BytesIO()
    output.name = "velocity_bingo_top10.jpg"
    # Downscale and use JPEG to reduce upload time to Telegram.
    image = image.resize((900, 675), Image.Resampling.LANCZOS)
    image.save(output, format="JPEG", quality=82, optimize=False, progressive=False)
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
