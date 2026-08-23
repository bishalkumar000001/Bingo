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
    await db["tournaments"].create_index("status")
    await db["tournaments"].create_index([("players", 1)])
    await db["chats"].create_index("chat_id", unique=True)


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




async def register_group_chat(chat_id: int, title: str = "", username: str = ""):
    """Remember a Telegram group/supergroup where the bot is installed/used."""
    if not chat_id:
        return
    await _col("chats").update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "title": title or "",
            "username": username or "",
            "updated_at": datetime.now(timezone.utc),
        }, "$setOnInsert": {
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def get_all_group_chat_ids() -> List[int]:
    """Return all known group/supergroup chat IDs for owner broadcasts.

    Includes chats explicitly registered and every chat that has ever hosted
    a Bingo room, so existing groups are not lost across restarts.
    """
    ids = set()
    docs = await _col("chats").find(
        {"chat_id": {"$exists": True}}, {"chat_id": 1, "_id": 0}
    ).to_list(length=None)
    ids.update(d["chat_id"] for d in docs if d.get("chat_id"))

    room_docs = await _col("rooms").find(
        {"chat_id": {"$exists": True}}, {"chat_id": 1, "_id": 0}
    ).to_list(length=None)
    ids.update(d["chat_id"] for d in room_docs if d.get("chat_id"))

    return list(ids)


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


async def log_game_result(telegram_id: int, chat_id: int, won: bool, coins: int = 0):
    await _col("game_results").insert_one({
        "telegram_id": telegram_id,
        "chat_id": chat_id,
        "won": won,
        "coins": coins,
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
    pipeline = [
        {"$match": {"games_played": {"$gt": 0}}},
        {"$sort": {"coins": -1, "wins": -1}},
        {"$limit": limit},
    ]
    cursor = _col("users").aggregate(pipeline)
    docs = await cursor.to_list(length=limit)
    return [_to_dict(d) for d in docs]


async def get_leaderboard_filtered(
    scope: str, chat_id: int, time_filter: str, limit: int = 10
) -> List[Dict]:
    # For global all-time leaderboard, use stored `users.coins` to preserve
    # historical totals that may not be reflected in `game_results`.
    if scope == "global" and time_filter == "all_time":
        return await get_leaderboard(limit)

    match: Dict = {"won": True}

    if scope == "chat" and chat_id:
        match["chat_id"] = chat_id

    start = _time_filter_start(time_filter)
    if start:
        match["created_at"] = {"$gte": start}

    # Aggregate wins and sum of coins awarded during the period from game_results
    pipeline = [
        {"$match": match},
        {"$group": {"_id": "$telegram_id", "wins": {"$sum": 1}, "coins": {"$sum": "$coins"}}},
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
            "wins": 1,
            "username": "$user_doc.username",
            "first_name": "$user_doc.first_name",
            "coins": 1,
            "games_played": "$user_doc.games_played",
        }},
        {"$sort": {"coins": -1, "wins": -1}},
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


async def deduct_coins_for_forfeit(user_id: int, amount: int) -> bool:
    """Atomically deduct *amount* coins from *user_id* only if they have enough.
    Returns True on success, False if the balance was insufficient."""
    result = await _col("users").update_one(
        {"telegram_id": user_id, "coins": {"$gte": amount}},
        {"$inc": {"coins": -amount}},
    )
    return result.modified_count > 0


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

async def add_coins(user_id: int, amount: int) -> bool:
    """Add coins to a user without deducting from anyone."""
    result = await _col("users").update_one(
        {"telegram_id": user_id},
        {"$inc": {"coins": amount}}
    )
    return result.modified_count > 0

async def find_user_by_username(username: str) -> Optional[Dict]:
    """Find a user by username."""
    doc = await _col("users").find_one({"username": username})
    return _to_dict(doc)

# ─────────────────────────────────────────────────────────────────────────────
# Tournament storage
# ─────────────────────────────────────────────────────────────────────────────

async def get_active_tournament() -> Optional[Dict]:
    doc = await _col("tournaments").find_one({"status": {"$in": ["registration", "active"]}})
    return _to_dict(doc)


async def get_tournament(tournament_id: str) -> Optional[Dict]:
    doc = await _col("tournaments").find_one({"_id": _oid(tournament_id)})
    return _to_dict(doc)


async def create_tournament(title: str, prize: str, start_at, max_players, rules: str, group_id: str) -> Dict:
    doc = {
        "title": title,
        "prize": prize,
        "start_at": start_at,
        "max_players": max_players,
        "rules": rules,
        "group_id": group_id,
        "players": [],
        "status": "registration",
        "current_round": 0,
        "rounds": [],
        "champion": None,
        "created_at": datetime.now(timezone.utc),
    }
    result = await _col("tournaments").insert_one(doc)
    doc["id"] = str(result.inserted_id)
    return doc


async def update_tournament(tournament_id: str, **kwargs):
    if not kwargs:
        return
    await _col("tournaments").update_one({"_id": _oid(tournament_id)}, {"$set": kwargs})


async def add_tournament_player(tournament_id: str, player_id: int, max_players: Optional[int] = None) -> bool:
    query = {"_id": _oid(tournament_id), "status": "registration", "players": {"$ne": player_id}}
    if max_players:
        query["$expr"] = {"$lt": [{"$size": "$players"}, max_players]}
    result = await _col("tournaments").update_one(query, {"$push": {"players": player_id}})
    return result.modified_count > 0


async def remove_tournament_player(tournament_id: str, player_id: int) -> bool:
    result = await _col("tournaments").update_one(
        {"_id": _oid(tournament_id), "status": "registration", "players": player_id},
        {"$pull": {"players": player_id}},
    )
    return result.modified_count > 0


async def append_tournament_round(tournament_id: str, round_no: int, matches: list, byes: list):
    await _col("tournaments").update_one(
        {"_id": _oid(tournament_id)},
        {"$push": {"rounds": {"round": round_no, "matches": matches, "byes": byes}}},
    )


async def set_tournament_match_winner(tournament_id: str, room_id: str, winner_id: int):
    await _col("tournaments").update_one(
        {"_id": _oid(tournament_id)},
        {"$set": {
            "rounds.$[].matches.$[match].winner": winner_id,
            "rounds.$[].matches.$[match].status": "finished",
        }},
        array_filters=[{"match.room_id": room_id}],
    )

# ── Simple tournament registration ───────────────────────────────────────────
async def create_active_tournament(source_chat_id: int, source_message_id: int, max_players: int = 64):
    await _col("simple_tournament_players").delete_many({})
    await _col("simple_tournament").update_one(
        {"key": "active"},
        {"$set": {"key": "active", "status": "active", "source_chat_id": source_chat_id,
                  "source_message_id": source_message_id, "max_players": max_players,
                  "created_at": datetime.now(timezone.utc)}}, upsert=True)

async def get_active_tournament():
    return _to_dict(await _col("simple_tournament").find_one({"key": "active", "status": "active"}))

async def join_active_tournament(telegram_id: int, username: str, first_name: str, max_players: int = 64):
    t = await get_active_tournament()
    if not t:
        return {"status": "inactive", "count": 0}
    existing = await _col("simple_tournament_players").find_one({"telegram_id": telegram_id})
    count = await _col("simple_tournament_players").count_documents({})
    if existing:
        return {"status": "already", "count": count}
    if count >= max_players:
        return {"status": "full", "count": count}
    await _col("simple_tournament_players").insert_one({
        "telegram_id": telegram_id, "username": username, "first_name": first_name,
        "joined_at": datetime.now(timezone.utc), "number": count + 1
    })
    return {"status": "joined", "count": count + 1}

async def get_tournament_players(tournament_id: str = ""):
    cursor = _col("simple_tournament_players").find({}).sort("number", 1)
    return [dict(x) async for x in cursor]

async def cancel_active_tournament():
    await _col("simple_tournament").update_one({"key": "active"}, {"$set": {"status": "cancelled"}})
    await _col("simple_tournament_players").delete_many({})
