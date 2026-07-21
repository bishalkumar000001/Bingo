from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import get_leaderboard_filtered

SCOPE_ICONS = {"global": "🌐 Global", "chat": "📍 Current Chat"}
TIME_ICONS = {
    "today": "🟡 Today",
    "week": "🟢 This Week",
    "month": "🔵 This Month",
    "year": "🟣 This Year",
    "all_time": "🏆 All Time",
}
# Label shown next to coins depending on scope+period
COINS_LABEL = {
    ("global", "today"):    "earned today (all groups)",
    ("global", "week"):     "earned this week (all groups)",
    ("global", "month"):    "earned this month (all groups)",
    ("global", "year"):     "earned this year (all groups)",
    ("global", "all_time"): "total coins",
    ("chat", "today"):      "earned today (this chat)",
    ("chat", "week"):       "earned this week (this chat)",
    ("chat", "month"):      "earned this month (this chat)",
    ("chat", "year"):       "earned this year (this chat)",
    ("chat", "all_time"):   "earned all time (this chat)",
}


def build_leaderboard_keyboard(scope: str, time_filter: str, chat_id: int) -> InlineKeyboardMarkup:
    def _btn(s: str, t: str, label: str) -> InlineKeyboardButton:
        active = s == scope and t == time_filter
        return InlineKeyboardButton(
            label + (" ✅" if active else ""),
            callback_data=f"lb:{s}:{t}:{chat_id}",
        )

    if chat_id:
        chat_btn = _btn("chat", time_filter, "📍 This Chat")
    else:
        chat_btn = InlineKeyboardButton("📍 This Chat", callback_data="lb_nochat")

    return InlineKeyboardMarkup([
        [chat_btn, _btn("global", time_filter, "🌐 Global")],
        [
            _btn(scope, "today",    "🟡 Today"),
            _btn(scope, "week",     "🟢 Week"),
            _btn(scope, "month",    "🔵 Month"),
        ],
        [
            _btn(scope, "year",     "🟣 Year"),
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
    if scope == "chat" and chat_title:
        scope_label = f"📍 {chat_title}"

    time_label  = TIME_ICONS[time_filter]
    coins_label = COINS_LABEL.get((scope, time_filter), "coins")

    header = (
        f"🏆 <b>Velocity Bingo — Leaderboard</b> 🏆\n"
        f"{scope_label}  |  {time_label}\n"
    )

    if not rows:
        period_map = {
            "today":    "today",
            "week":     "this week",
            "month":    "this month",
            "year":     "this year",
            "all_time": "yet",
        }
        period_str = period_map.get(time_filter, "yet")
        where = "in this chat" if scope == "chat" else "globally"
        return header + f"\n📭 No coins earned {where} {period_str}."

    lines = [header, "━━━━━━━━━━━━━━━━━━━━"]
    emojis = ["💎", "👑", "⭐", "✨", "🌟", "💫", "🎯", "🎖️", "🏅", "🎁"]

    for rank, row in enumerate(rows, start=1):
        name  = _name(row)
        # all_time global uses 'coins' field; all other combos use 'coins_earned'
        coins = row.get("coins_earned") if row.get("coins_earned") is not None else row.get("coins", 0)
        emoji = emojis[(rank - 1) % len(emojis)]

        if rank == 1:
            rank_str = "🥇"
        elif rank == 2:
            rank_str = "🥈"
        elif rank == 3:
            rank_str = "🥉"
        else:
            rank_str = f"{rank}."

        lines.append(f"{rank_str} <b>{name}</b> {emoji} — 💰 <b>{coins:,}</b>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"<i>Showing: {coins_label}</i>")
    return "\n".join(lines)

