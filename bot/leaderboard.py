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
    """Create a dynamic Top-10 bar-chart image using live leaderboard data."""
    rows = await get_leaderboard_filtered(scope, chat_id, time_filter, limit=10)

    width = 1200
    height = 220 + max(1, len(rows)) * 125 + 120
    image = Image.new("RGB", (width, height), "#070b14")
    draw = ImageDraw.Draw(image)

    title_font = _font(62, True)
    sub_font = _font(30, True)
    name_font = _font(34, True)
    coin_font = _font(31, True)
    small_font = _font(25, True)

    # Header
    draw.rounded_rectangle((20, 20, width - 20, 185), radius=28, fill="#0b1323", outline="#d6a72d", width=3)
    draw.text((width // 2, 42), "🏆 VELOCITY BINGO", font=title_font, anchor="ma", fill="#f7c948")
    scope_text = chat_title if scope == "chat" and chat_title else ("GLOBAL" if scope == "global" else "CURRENT CHAT")
    draw.text((width // 2, 120), f"TOP 10 PLAYERS • {scope_text} • {TIME_ICONS[time_filter]}", font=sub_font, anchor="ma", fill="#e8edf7")

    if not rows:
        draw.text((width // 2, height // 2), "No leaderboard scores yet", font=title_font, anchor="mm", fill="#d8dee9")
    else:
        max_coins = max(max(int(r.get("coins", 0) or 0) for r in rows), 1)
        bar_colors = ["#f5b700", "#b9c0c8", "#cd7f32", "#8e44ad", "#d63384", "#e67e22", "#16a085", "#2980b9", "#7f8c8d", "#6c5ce7"]
        medals = ["🥇", "🥈", "🥉"]

        y = 205
        for rank, row in enumerate(rows, start=1):
            row_top = y
            row_bottom = y + 105
            draw.rounded_rectangle((25, row_top, width - 25, row_bottom), radius=20, fill="#101827", outline="#26344a", width=2)

            badge = medals[rank - 1] if rank <= 3 else f"#{rank}"
            draw.rounded_rectangle((45, row_top + 18, 135, row_bottom - 18), radius=14, fill="#172238")
            draw.text((90, y + 52), badge, font=sub_font, anchor="mm", fill="#ffffff")

            name = _fit_name(_display_name(row))
            draw.text((165, y + 52), name, font=name_font, anchor="lm", fill="#f4f7fb")

            bar_x1, bar_x2 = 470, 930
            draw.rounded_rectangle((bar_x1, y + 27, bar_x2, y + 78), radius=14, fill="#1e2938")
            coins = int(row.get("coins", 0) or 0)
            bar_end = bar_x1 + max(20, int((bar_x2 - bar_x1) * coins / max_coins))
            draw.rounded_rectangle((bar_x1, y + 27, bar_end, y + 78), radius=14, fill=bar_colors[rank - 1])
            draw.text((bar_end - 15 if bar_end > bar_x1 + 120 else bar_x1 + 15, y + 52), f"{coins:,}", font=small_font, anchor="rm" if bar_end > bar_x1 + 120 else "lm", fill="#ffffff")

            draw.text((1150, y + 52), f"${coins:,}", font=coin_font, anchor="rm", fill="#f7c948")
            y += 120

    draw.rounded_rectangle((25, height - 95, width - 25, height - 25), radius=18, fill="#0b1323", outline="#d6a72d", width=2)
    draw.text((width // 2, height - 60), "PLAY MORE • WIN MORE • CLIMB THE RANKINGS!", font=sub_font, anchor="mm", fill="#f7c948")

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
