import os
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta

import motor.motor_asyncio
from bson import ObjectId

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = "velocity_bingo"

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None


def _get_db():
    global _client
    if _client is None:
        _client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    return _client[DB_NAME]


def _col(name: str):
    return _get_db()[name]


def _to_dict(doc) -> Optional[Dict]:
    if doc is None:
        return None
    d = dict(doc)
    d["id"] = str(d.pop("_id"))
    return d


def _oid(id_str: str) -> ObjectId:
    return ObjectId(id_str)


async def init_db():
    db = _get_db()
    await db["users"].create_index("telegram_id", unique=True)
    await db["rooms"].create_index([("chat_id", 1), ("status", 1)])
    await db["rooms"].create_index([("player1_id", 1), ("status", 1)])
    await db["rooms"].create_index([("player2_id", 1), ("status", 1)])
    await db["cards"].create_index([("room_id", 1), ("player_id", 1)])
    await db["game_results"].create_index([("telegram_id", 1), ("created_at", -1)])
    await db["game_results"].create_index([("chat_id", 1), ("created_at", -1)])
    await db["game_results"].create_index([("won", 1), ("created_at", -1)])


async def get_user(telegram_id: int) -> Optional[Dict]:
    doc = await _col("users").find_one({"telegram_id": telegram_id})
    return _to_dict(doc)


async def create_user(telegram_id: int, username: str, first_name: str):
    await _col("users").update_one(
        {"telegram_id": telegram_id},
        {"$set": {
            "telegram_id": telegram_id,
            "username": username or "",
            "first_name": first_name or "",
        }, "$setOnInsert": {
            "coins": 0,
            "games_played": 0,
            "wins": 0,
            "losses": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def get_all_user_ids() -> List[int]:
    cursor = _col("users").find({}, {"telegram_id": 1, "_id": 0})
    docs = await cursor.to_list(length=None)
    return [d["telegram_id"] for d in docs]


async def get_active_rooms_in_chat(chat_id: int) -> List[Dict]:
    cursor = _col("rooms").find({"chat_id": chat_id, "status": {"$in": ["waiting", "playing"]}})
    docs = await cursor.to_list(length=10)
    return [_to_dict(d) for d in docs]


async def get_next_room_number(chat_id: int) -> int:
    active = await get_active_rooms_in_chat(chat_id)
    used = {r["room_number"] for r in active}
    for n in range(1, 4):
        if n not in used:
            return n
    return -1


async def is_player_in_active_room(player_id: int) -> bool:
    doc = await _col("rooms").find_one({
        "status": {"$in": ["waiting", "playing"]},
        "$or": [{"player1_id": player_id}, {"player2_id": player_id}],
    })
    return doc is not None


async def create_room(chat_id: int, room_number: int, player1_id: int,
                      room_message_id: int, stake_amount: int = 0) -> str:
    result = await _col("rooms").insert_one({
        "room_number": room_number,
        "chat_id": chat_id,
        "player1_id": player1_id,
        "player2_id": None,
        "status": "waiting",
        "current_turn": None,
        "phase": "call",
        "last_called_number": None,
        "called_numbers": [],
        "live_message_id": None,
        "last_call_message_id": None,
        "group_panel_message_id": None,
        "room_message_id": room_message_id,
        "stake_amount": stake_amount,
        "created_at": datetime.now(timezone.utc),
    })
    return str(result.inserted_id)


async def get_room(room_id: str) -> Optional[Dict]:
    doc = await _col("rooms").find_one({"_id": _oid(room_id)})
    return _to_dict(doc)


async def update_room(room_id: str, **kwargs):
    if not kwargs:
        return
    await _col("rooms").update_one({"_id": _oid(room_id)}, {"$set": kwargs})


async def join_room(room_id: str, player2_id: int):
    await _col("rooms").update_one(
        {"_id": _oid(room_id), "status": "waiting"},
        {"$set": {"player2_id": player2_id, "status": "playing"}},
    )


async def create_card(room_id: str, player_id: int, numbers: List[int]) -> str:
    result = await _col("cards").insert_one({
        "room_id": room_id,
        "player_id": player_id,
        "numbers": numbers,
        "marked_numbers": [],
        "completed_lines": 0,
        "card_message_id": None,
    })
    return str(result.inserted_id)


async def get_card(room_id: str, player_id: int) -> Optional[Dict]:
    doc = await _col("cards").find_one({"room_id": room_id, "player_id": player_id})
    return _to_dict(doc)


async def mark_number(card_id: str, number: int, new_lines: int):
    await _col("cards").update_one(
        {"_id": _oid(card_id)},
        {"$addToSet": {"marked_numbers": number}, "$set": {"completed_lines": new_lines}},
    )


async def update_card_message_id(card_id: str, message_id: int):
    await _col("cards").update_one(
        {"_id": _oid(card_id)},
        {"$set": {"card_message_id": message_id}},
    )


async def log_game_result(telegram_id: int, chat_id: int, won: bool, coins_earned: int = 0):
    """
    Record the outcome of a game.
    coins_earned: net coins gained this game (e.g. WIN_COINS + stake for winner,
                  or -stake for loser). Pass 0 for no-stake losses.
    Old records without coins_earned default to 0 in aggregations.
    """
    await _col("game_results").insert_one({
        "telegram_id": telegram_id,
        "chat_id": chat_id,
        "won": won,
        "coins_earned": coins_earned,
        "created_at": datetime.now(timezone.utc),
    })


def _time_filter_start(time_filter: str) -> Optional[datetime]:
    now = datetime.now(timezone.utc)
    if time_filter == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_filter == "week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_filter == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif time_filter == "year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


async def get_leaderboard(limit: int = 10) -> List[Dict]:
    """All-time global leaderboard by total coins held."""
    pipeline = [
        {"$match": {"games_played": {"$gt": 0}}},
        {"$sort": {"coins": -1, "wins": -1}},
        {"$limit": limit},
    ]
    cursor = _col("users").aggregate(pipeline)
    docs = await cursor.to_list(length=limit)
    return [_to_dict(d) for d in docs]


async def get_leaderboard_filtered(
    scope: str,
    chat_id: int,
    time_filter: str,
    limit: int = 10,
) -> List[Dict]:
    """
    Leaderboard filtered by scope (global / chat) and time period.

    - scope="global", time_filter="all_time": total coins held (from users collection)
    - all other combos: coins EARNED in the given period (from game_results.coins_earned)

    Each row has: telegram_id, username, first_name, coins (earned in period).
    """

    # Special case: global all-time → use total coins on the user record
    if scope == "global" and time_filter == "all_time":
        rows = await get_leaderboard(limit)
        # Rename field so the display layer uses a consistent key
        for r in rows:
            r["coins_earned"] = r.get("coins", 0)
        return rows

    # All other cases: sum coins_earned from game_results
    match: Dict = {}

    if scope == "chat" and chat_id:
        match["chat_id"] = chat_id

    start = _time_filter_start(time_filter)
    if start:
        match["created_at"] = {"$gte": start}

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$telegram_id",
            "coins_earned": {"$sum": {"$ifNull": ["$coins_earned", 0]}},
            "wins": {"$sum": {"$cond": ["$won", 1, 0]}},
        }},
        # Only show players who earned at least 1 coin in this period
        {"$match": {"coins_earned": {"$gt": 0}}},
        {"$lookup": {
            "from": "users",
            "localField": "_id",
            "foreignField": "telegram_id",
            "as": "user_doc",
        }},
        {"$unwind": "$user_doc"},
        {"$project": {
            "_id": 0,
            "telegram_id": "$_id",
            "coins_earned": 1,
            "wins": 1,
            "username": "$user_doc.username",
            "first_name": "$user_doc.first_name",
        }},
        {"$sort": {"coins_earned": -1, "wins": -1}},
        {"$limit": limit},
    ]

    cursor = _col("game_results").aggregate(pipeline)
    return await cursor.to_list(length=limit)


async def update_user_stats(telegram_id: int, won: bool, coins_delta: int):
    user = await get_user(telegram_id)
    if not user:
        return

    new_streak = user["current_streak"] + 1 if won else 0
    new_longest = max(user["longest_streak"], new_streak)

    await _col("users").update_one(
        {"telegram_id": telegram_id},
        {"$inc": {
            "games_played": 1,
            "wins": 1 if won else 0,
            "losses": 0 if won else 1,
            "coins": coins_delta,
        }, "$set": {
            "current_streak": new_streak,
            "longest_streak": new_longest,
        }},
    )


async def cancel_room(room_id: str):
    await _col("rooms").update_one(
        {"_id": _oid(room_id)},
        {"$set": {"status": "cancelled"}},
    )


async def finish_room(room_id: str):
    await _col("rooms").update_one(
        {"_id": _oid(room_id)},
        {"$set": {"status": "finished"}},
    )


async def get_player_active_room(player_id: int) -> Optional[Dict]:
    doc = await _col("rooms").find_one({
        "status": {"$in": ["waiting", "playing"]},
        "$or": [{"player1_id": player_id}, {"player2_id": player_id}],
    })
    return _to_dict(doc)


async def transfer_coins(from_id: int, to_id: int, amount: int) -> bool:
    """Transfer coins from one user to another. Returns True if successful."""
    sender = await get_user(from_id)
    receiver = await get_user(to_id)

    if not sender or not receiver:
        return False

    if sender["coins"] < amount:
        return False

    await _col("users").update_one(
        {"telegram_id": from_id},
        {"$inc": {"coins": -amount}},
    )
    await _col("users").update_one(
        {"telegram_id": to_id},
        {"$inc": {"coins": amount}},
    )
    return True


async def find_user_by_username(username: str) -> Optional[Dict]:
    """Find a user by username."""
    doc = await _col("users").find_one({"username": username})
    return _to_dict(doc)

