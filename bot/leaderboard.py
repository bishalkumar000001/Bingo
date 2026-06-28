from database import get_leaderboard
from utils import display_name_from_db, medal


async def build_leaderboard_text() -> str:
    rows = await get_leaderboard(limit=10)
    if not rows:
        return "📊 <b>Leaderboard</b>\n\nNo games played yet. Be the first to play!"

    lines = ["🏆 <b>Velocity Bingo — Leaderboard</b>\n"]
    for rank, row in enumerate(rows, start=1):
        name = display_name_from_db(row)
        win_rate = (row["wins"] / row["games_played"] * 100) if row["games_played"] > 0 else 0
        lines.append(
            f"{medal(rank)} <b>{name}</b>\n"
            f"   🏅 Wins: {row['wins']}  |  💰 Coins: {row['coins']:,}\n"
            f"   🎮 Games: {row['games_played']}  |  📈 Win Rate: {win_rate:.1f}%\n"
            f"{'─' * 28}"
        )
    return "\n".join(lines)
