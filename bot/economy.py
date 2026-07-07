import database as db
from models import WIN_COINS


async def award_winner(winner_id: int, chat_id: int = 0):
    await db.update_user_stats(winner_id, won=True, coins_delta=WIN_COINS)
    if chat_id:
        await db.log_game_result(winner_id, chat_id, won=True)


async def record_loss(loser_id: int, chat_id: int = 0):
    await db.update_user_stats(loser_id, won=False, coins_delta=0)
    if chat_id:
        await db.log_game_result(loser_id, chat_id, won=False)



