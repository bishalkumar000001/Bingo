from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import get_leaderboard_filtered
from utils import medal

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


def _name(row: dict) -> str:
    if row.get("username"):
        return f"@{row['username']}"
    return row.get("first_name") or str(row.get("telegram_id", "?"))


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

    header = f"🏆 <b>Velocity Bingo — Leaderboard</b>\n{scope_label}  |  {time_label}\n"

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

    lines = [header]
    for rank, row in enumerate(rows, start=1):
        name = _name(row)
        wins = row.get("wins", 0)
        coins = row.get("coins", 0)
        games = row.get("games_played", 0)
        win_rate = (wins / games * 100) if games > 0 else 0.0
        lines.append(
            f"{medal(rank)} <b>{name}</b>\n"
            f"   🏅 Wins: {wins}  |  💰 Coins: {coins:,}\n"
            f"   🎮 Games: {games}  |  📈 Win Rate: {win_rate:.1f}%\n"
            f"{'─' * 28}"
        )
    return "\n".join(lines)
