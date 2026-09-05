from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import get_leaderboard_filtered
from html import escape

SCOPE_ICONS = {"global": "🌐 Global", "chat": "📍 Current Chat"}
TIME_ICONS = {
    "today": "🟡 Today",
    "week": "🟡 Week",
    "month": "🔵 Month",
    "year": "🟣 This Year",
    "all_time": "🏆 All Time",
}


def build_leaderboard_keyboard(scope: str, time_filter: str, chat_id: int) -> InlineKeyboardMarkup:
    def _btn(s: str, t: str, label: str) -> InlineKeyboardButton:
        active = s == scope and t == time_filter
        return InlineKeyboardButton(label + (" ✅" if active else ""), callback_data=f"lb:{s}:{t}:{chat_id}")

    chat_btn = _btn("chat", time_filter, "📍 Current Chat") if chat_id else InlineKeyboardButton("📍 Current Chat", callback_data="lb_nochat")
    return InlineKeyboardMarkup([
        [chat_btn, _btn("global", time_filter, "🌐 Global")],
        [_btn(scope, "today", "🟡 Today"), _btn(scope, "week", "🟡 Week"), _btn(scope, "month", "🔵 Month")],
        [_btn(scope, "year", "🟣 This Year"), _btn(scope, "all_time", "🏆 All Time")],
    ])


def _name(row: dict) -> str:
    user_id = row.get("telegram_id")
    display_name = row.get("first_name") or str(user_id)
    if len(display_name) > 15:
        display_name = display_name[:15] + "…"
    return f'<a href="tg://user?id={user_id}">{escape(display_name)}</a>'


async def build_leaderboard_text(scope: str = "global", time_filter: str = "all_time", chat_id: int = 0, chat_title: str = "") -> str:
    rows = await get_leaderboard_filtered(scope, chat_id, time_filter)
    scope_label = f"📍 {chat_title}" if scope == "chat" and chat_title else SCOPE_ICONS[scope]
    time_label = TIME_ICONS[time_filter]

    metric = "Total Wealth" if time_filter == "all_time" else "Net Coins"
    header = (
        "<blockquote>"
        f"💎 <b>Velocity Bingo — Economy Leaderboard</b>\n"
        f"{scope_label}  •  {time_label}\n"
        f"📊 Ranked by <b>{metric}</b>"
        "</blockquote>"
    )

    if not rows:
        period_map = {"today": "today", "week": "this week", "month": "this month", "year": "this year", "all_time": "yet"}
        where = "in this chat" if scope == "chat" else "globally"
        return header + f"\n📭 No economy activity recorded {where} {period_map.get(time_filter, 'yet')}."

    lines = [header, "<blockquote>"]
    for rank, row in enumerate(rows, start=1):
        name = _name(row)
        coins = int(row.get("coins", 0) or 0)
        display_coins = f"{coins:+,}" if time_filter != "all_time" else f"{coins:,}"
        if rank == 1:
            lines.append(f"🥇 <b>{name}</b>  <b>{display_coins}</b>")
        elif rank == 2:
            lines.append(f"🥈 <b>{name}</b>  <b>{display_coins}</b>")
        elif rank == 3:
            lines.append(f"🥉 <b>{name}</b>  <b>{display_coins}</b>")
        else:
            lines.append(f"{rank}. <b>{name}</b>  <b>{display_coins}</b>")
    lines.append("</blockquote>")
    if time_filter != "all_time":
        lines.append("\n💡 <i>Period rankings use net Bingo Coin movement from economy activity.</i>")
    else:
        lines.append("\n💰 <i>All Time ranks players by their current wallet + bank wealth.</i>")
    return "\n".join(lines)
