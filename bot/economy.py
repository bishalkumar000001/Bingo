import database as db
from models import WIN_COINS, FORFEIT_COST


async def award_winner(winner_id: int, chat_id: int = 0):
    await db.update_user_stats(winner_id, won=True, coins_delta=WIN_COINS)
    if chat_id:
        await db.log_game_result(winner_id, chat_id, won=True, coins=WIN_COINS)


async def record_loss(loser_id: int, chat_id: int = 0):
    await db.update_user_stats(loser_id, won=False, coins_delta=0)
    if chat_id:
        await db.log_game_result(loser_id, chat_id, won=False, coins=0)

async def process_forfeit(forfeiter_id: int, chat_id: int = 0) -> bool:
    """Deduct FORFEIT_COST from forfeiter. Opponent receives nothing.
    Returns True if the deduction succeeded (player had enough coins),
    False if the player lacked funds (caller should block the forfeit)."""
    success = await db.deduct_coins_for_forfeit(forfeiter_id, FORFEIT_COST)
    if not success:
        return False
    # Record as a loss; no coins awarded to opponent
    await db.update_user_stats(forfeiter_id, won=False, coins_delta=0)
    if chat_id:
        await db.log_game_result(forfeiter_id, chat_id, won=False, coins=0)
    return True



