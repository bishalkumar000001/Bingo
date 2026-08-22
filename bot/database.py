import os
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta

import motor.motor_asyncio
from bson import ObjectId
from pymongo import ReturnDocument

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = "velocity_bingo"

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None


def _get_db():
    global _client
    if _client is None:
        _client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGODB_URI,
            maxPoolSize=int(os.environ.get("MONGO_MAX_POOL_SIZE", "100")),
            minPoolSize=int(os.environ.get("MONGO_MIN_POOL_SIZE", "10")),
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            waitQueueTimeoutMS=3000,
            maxIdleTimeMS=120000,
            retryWrites=True,
        )
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
    await db["rooms"].create_index([("chat_id", 1), ("room_number", 1), ("status", 1)])
    await db["rooms"].create_index([("status", 1), ("current_turn", 1)])
    await db["rooms"].create_index([("status", 1), ("player1_id", 1)])
    await db["rooms"].create_index([("status", 1), ("player2_id", 1)])
    await db["tournament_matches"].create_index([("tournament_id", 1), ("round", 1), ("status", 1)])
    await db["cards"].create_index([("room_id", 1), ("player_id", 1)])
    await db["game_results"].create_index([("telegram_id", 1), ("created_at", -1)])
    await db["game_results"].create_index([("chat_id", 1), ("created_at", -1)])
    await db["game_results"].create_index([("won", 1), ("created_at", -1)])
    await db["known_groups"].create_index("chat_id", unique=True)
    await db["tournaments"].create_index([("status", 1), ("created_at", -1)])
    await db["tournament_matches"].create_index([("tournament_id", 1), ("round", 1)])
    await db["tournament_matches"].create_index([("tournament_id", 1), ("round", 1), ("status", 1), ("match_number", 1)])
    await db["tournament_cards"].create_index([("match_id", 1), ("player_id", 1)], unique=True)


async def register_group(chat_id: int, title: str = "", username: str = ""):
    await _col("known_groups").update_one(
        {"chat_id": chat_id},
        {"$set": {"chat_id": chat_id, "title": title or "", "username": username or "", "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def get_all_group_ids() -> List[int]:
    docs = await _col("known_groups").find({}, {"chat_id": 1, "_id": 0}).to_list(length=None)
    return [d["chat_id"] for d in docs]


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
    max_rooms = max(1, int(os.environ.get("MAX_ROOMS_PER_CHAT", "10")))
    for n in range(1, max_rooms + 1):
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


async def claim_call(room_id: str, player_id: int, number: int) -> Optional[Dict]:
    doc = await _col("rooms").find_one_and_update(
        {"_id": _oid(room_id), "status": "playing", "phase": "call",
         "current_turn": player_id, "called_numbers": {"$ne": number}},
        {"$push": {"called_numbers": number},
         "$set": {"last_called_number": number, "phase": "mark"}},
        return_document=ReturnDocument.AFTER,
    )
    return _to_dict(doc)

async def claim_mark(card_id: str, number: int, new_lines: int) -> bool:
    result = await _col("cards").update_one(
        {"_id": _oid(card_id), "marked_numbers": {"$ne": number}},
        {"$addToSet": {"marked_numbers": number}, "$set": {"completed_lines": new_lines}},
    )
    return result.modified_count == 1

async def transition_mark_to_call(room_id: str, marker_id: int) -> Optional[Dict]:
    doc = await _col("rooms").find_one_and_update(
        {"_id": _oid(room_id), "status": "playing", "phase": "mark", "marker_id": marker_id},
        {"$set": {"current_turn": marker_id, "phase": "call"}},
        return_document=ReturnDocument.AFTER,
    )
    return _to_dict(doc)

async def join_room(room_id: str, player2_id: int):
    await _col("rooms").update_one(
        {"_id": _oid(room_id), "status": "waiting"},
        {"$set": {"player2_id": player2_id, "status": "playing"}},
    )


async def create_card(room_id: str, player_id: int, numbers: List[int]) -> str:
    await _col("cards").update_one(
        {"room_id": room_id, "player_id": player_id},
        {"$setOnInsert": {"room_id": room_id, "player_id": player_id,
                          "numbers": numbers, "marked_numbers": [],
                          "completed_lines": 0, "card_message_id": None}},
        upsert=True,
    )
    doc = await _col("cards").find_one({"room_id": room_id, "player_id": player_id})
    return str(doc["_id"])


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


# ---------------- Tournament storage ----------------
async def create_tournament(data: Dict, owner_id: int) -> str:
    doc = dict(data)
    doc.update({"owner_id": owner_id, "status": "registration", "winner_id": None,
                "current_round": 0, "created_at": datetime.now(timezone.utc)})
    result = await _col("tournaments").insert_one(doc)
    return str(result.inserted_id)

async def get_tournament(tournament_id: str) -> Optional[Dict]:
    try: doc = await _col("tournaments").find_one({"_id": _oid(tournament_id)})
    except Exception: return None
    return _to_dict(doc)

async def update_tournament(tournament_id: str, **kwargs):
    await _col("tournaments").update_one({"_id": _oid(tournament_id)}, {"$set": kwargs})

async def add_tournament_player(tournament_id: str, user_id: int) -> Optional[int]:
    """Atomically register a player and return their 1-based registration number.

    Returning the updated document makes the registration count safe when two
    players press Join at nearly the same time. Returns None if already
    registered or the tournament was not found.
    """
    doc = await _col("tournaments").find_one_and_update(
        {"_id": _oid(tournament_id), "players": {"$ne": user_id}},
        {"$push": {"players": user_id}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        return None
    players = doc.get("players", [])
    try:
        return players.index(user_id) + 1
    except ValueError:
        return None

async def get_latest_tournament_id() -> Optional[str]:
    doc = await _col("tournaments").find_one({}, sort=[("created_at", -1)])
    return str(doc["_id"]) if doc else None

async def create_tournament_match(tournament_id: str, round_no: int, p1: int, p2: Optional[int], match_number: int = 1, status: str = "pending") -> str:
    r = await _col("tournament_matches").insert_one({"tournament_id": tournament_id,"round":round_no,"match_number":match_number,"p1":p1,"p2":p2,"status":status,"current_turn":p1,"phase":"call","called_numbers":[],"last_called":None,"marker_id":None,"winner_id":None,"loser_id":None,"group_message_id":None,"created_at":datetime.now(timezone.utc)})
    return str(r.inserted_id)

async def create_tournament_bye(tournament_id: str, round_no: int, player_id: int):
    await _col("tournament_matches").insert_one({"tournament_id":tournament_id,"round":round_no,"match_number":0,"p1":player_id,"p2":None,"status":"bye","winner_id":player_id,"created_at":datetime.now(timezone.utc)})

async def get_tournament_match(match_id: str) -> Optional[Dict]:
    try: doc=await _col("tournament_matches").find_one({"_id":_oid(match_id)})
    except Exception: return None
    return _to_dict(doc)

async def update_tournament_match(match_id: str, **kwargs):
    await _col("tournament_matches").update_one({"_id":_oid(match_id)}, {"$set":kwargs})

async def claim_tournament_call(match_id: str, player_id: int, number: int) -> Optional[Dict]:
    doc = await _col("tournament_matches").find_one_and_update(
        {"_id": _oid(match_id), "status": "playing", "phase": "call",
         "current_turn": player_id, "called_numbers": {"$ne": number}},
        {"$push": {"called_numbers": number},
         "$set": {"last_called": number, "phase": "mark"}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is not None:
        marker = doc.get("p2") if player_id == doc.get("p1") else doc.get("p1")
        await _col("tournament_matches").update_one({"_id": doc["_id"]}, {"$set": {"marker_id": marker}})
        doc["marker_id"] = marker
    return _to_dict(doc)

async def claim_tournament_mark(card_id: str, number: int, new_lines: int) -> bool:
    result = await _col("tournament_cards").update_one(
        {"_id": _oid(card_id), "marked_numbers": {"$ne": number}},
        {"$addToSet": {"marked_numbers": number}, "$set": {"completed_lines": new_lines}},
    )
    return result.modified_count == 1

async def transition_tournament_mark_to_call(match_id: str, player_id: int) -> Optional[Dict]:
    doc = await _col("tournament_matches").find_one_and_update(
        {"_id": _oid(match_id), "status": "playing", "phase": "mark", "marker_id": player_id},
        {"$set": {"current_turn": player_id, "phase": "call"}},
        return_document=ReturnDocument.AFTER,
    )
    return _to_dict(doc)

async def get_tournament_matches(tournament_id: str, round_no: int) -> List[Dict]:
    docs=await _col("tournament_matches").find({"tournament_id":tournament_id,"round":round_no}).sort("match_number",1).to_list(length=None)
    return [_to_dict(d) for d in docs]

async def clear_tournament_matches(tournament_id: str):
    await _col("tournament_matches").delete_many({"tournament_id":tournament_id})

async def clear_round_matches(tournament_id: str, round_no: int):
    await _col("tournament_matches").delete_many({"tournament_id":tournament_id,"round":round_no})

async def create_tournament_card(match_id: str, player_id: int, numbers: List[int]):
    await _col("tournament_cards").update_one(
        {"match_id": match_id, "player_id": player_id},
        {"$setOnInsert": {"match_id": match_id, "player_id": player_id, "numbers": numbers,
                          "marked_numbers": [], "completed_lines": 0, "card_message_id": None}},
        upsert=True,
    )

async def get_tournament_card(match_id: str, player_id: int) -> Optional[Dict]:
    doc=await _col("tournament_cards").find_one({"match_id":match_id,"player_id":player_id})
    return _to_dict(doc)

async def update_tournament_card(card_id: str, **kwargs):
    await _col("tournament_cards").update_one({"_id":_oid(card_id)}, {"$set":kwargs})

async def cancel_running_tournaments():
    await _col("tournaments").update_many({"status":"running"},{"$set":{"status":"interrupted"}})

async def get_running_tournaments() -> List[Dict]:
    docs=await _col("tournaments").find({"status":"running"}).to_list(length=None)
    return [_to_dict(d) for d in docs]
