from database import update_user_stats
from models import WIN_COINS


async def award_winner(winner_id: int):
    await update_user_stats(winner_id, won=True, coins_delta=WIN_COINS)


async def record_loss(loser_id: int):
    await update_user_stats(loser_id, won=False, coins_delta=0)
