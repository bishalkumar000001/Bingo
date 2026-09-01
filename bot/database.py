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
        _client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
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
    await db["cards"].create_index([("room_id", 1), ("player_id", 1)])
    await db["game_results"].create_index([("telegram_id", 1), ("created_at", -1)])
    await db["game_results"].create_index([("chat_id", 1), ("created_at", -1)])
    await db["game_results"].create_index([("won", 1), ("created_at", -1)])
    await db["tournaments"].create_index("status")
    await db["tournaments"].create_index([("players", 1)])
    await db["tournaments"].create_index([("created_at", -1)])
    await db["tournament_players"].create_index(
        [("tournament_id", 1), ("telegram_id", 1)], unique=True
    )
    await db["tournament_matches"].create_index(
        [("tournament_id", 1), ("round", 1), ("status", 1)]
    )
    await db["tournament_matches"].create_index([("room_id", 1)])
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


async def create_room(chat_id: int, room_number, player1_id: int,
                      room_message_id: int, stake_amount: int = 0,
                      tournament_id: Optional[str] = None,
                      tournament_round: Optional[int] = None,
                      tournament_match_id: Optional[str] = None) -> str:
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
        "tournament_id": tournament_id,
        "tournament_round": tournament_round,
        "tournament_match_id": tournament_match_id,
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


async def join_room(room_id: str, player2_id: int) -> bool:
    result = await _col("rooms").update_one(
        {"_id": _oid(room_id), "status": "waiting"},
        {"$set": {"player2_id": player2_id, "status": "playing"}},
    )
    return result.modified_count > 0


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
    doc = await _col("tournaments").find_one(
        {"status": {"$in": ["registration", "active"]}},
        sort=[("created_at", -1)],
    )
    return _to_dict(doc)


async def get_tournament(tournament_id: str) -> Optional[Dict]:
    doc = await _col("tournaments").find_one({"_id": _oid(tournament_id)})
    return _to_dict(doc)


async def create_tournament(
    title: str,
    prize_coins: int,
    max_players: int,
    rules: str,
    group_id: int,
    created_by: int,
    entry_fee: int = 0,
    registration_message_id: Optional[int] = None,
    announcement_text: str = "",
) -> Dict:
    doc = {
        "title": title,
        "prize_coins": prize_coins,
        "max_players": max_players,
        "rules": rules,
        "group_id": group_id,
        "created_by": created_by,
        "entry_fee": entry_fee,
        "players": [],
        "status": "registration",
        "current_round": None,
        "registration_message_id": registration_message_id,
        "announcement_text": announcement_text or "",
        "champion": None,
        "prize_paid": False,
        "created_at": datetime.now(timezone.utc),
    }
    result = await _col("tournaments").insert_one(doc)
    doc["id"] = str(result.inserted_id)
    return doc


async def update_tournament(tournament_id: str, **kwargs):
    if not kwargs:
        return
    await _col("tournaments").update_one({"_id": _oid(tournament_id)}, {"$set": kwargs})


async def count_tournament_players(tournament_id: str) -> int:
    return await _col("tournament_players").count_documents(
        {"tournament_id": _oid(tournament_id)}
    )


async def get_tournament_players(tournament_id: str):
    cursor = _col("tournament_players").find(
        {"tournament_id": _oid(tournament_id)}
    ).sort("joined_at", 1)
    return [dict(x) async for x in cursor]


async def join_tournament(
    tournament_id: str, telegram_id: int, username: str, first_name: str
) -> Dict:
    tournament = await get_tournament(tournament_id)
    if not tournament or tournament.get("status") != "registration":
        return {"status": "inactive", "count": 0}

    existing = await _col("tournament_players").find_one(
        {"tournament_id": _oid(tournament_id), "telegram_id": telegram_id}
    )
    if existing:
        return {"status": "already", "count": await count_tournament_players(tournament_id)}

    count = await count_tournament_players(tournament_id)
    if count >= tournament["max_players"]:
        return {"status": "full", "count": count}

    fee = max(0, int(tournament.get("entry_fee", 0) or 0))
    if fee:
        charged = await _col("users").update_one(
            {"telegram_id": telegram_id, "coins": {"$gte": fee}},
            {"$inc": {"coins": -fee}},
        )
        if not charged.modified_count:
            return {"status": "insufficient_funds", "count": count, "fee": fee}

    reserved = await _col("tournaments").update_one(
        {
            "_id": _oid(tournament_id),
            "status": "registration",
            "players": {"$ne": telegram_id},
            "$expr": {"$lt": [{"$size": "$players"}, tournament["max_players"]]},
        },
        {"$addToSet": {"players": telegram_id}},
    )
    if not reserved.modified_count:
        if fee:
            await _col("users").update_one(
                {"telegram_id": telegram_id}, {"$inc": {"coins": fee}}
            )
        return {"status": "full", "count": await count_tournament_players(tournament_id)}

    entry = {
        "tournament_id": _oid(tournament_id),
        "telegram_id": telegram_id,
        "username": username or "",
        "first_name": first_name or "",
        "entry_fee": fee,
        "refunded": False,
        "joined_at": datetime.now(timezone.utc),
    }
    try:
        inserted = await _col("tournament_players").insert_one(entry)
    except Exception:
        await _col("tournaments").update_one(
            {"_id": _oid(tournament_id)}, {"$pull": {"players": telegram_id}}
        )
        if fee:
            await _col("users").update_one(
                {"telegram_id": telegram_id}, {"$inc": {"coins": fee}}
            )
        return {"status": "already", "count": await count_tournament_players(tournament_id)}
    return {
        "status": "joined",
        "count": await count_tournament_players(tournament_id),
        "entry_id": str(inserted.inserted_id),
        "fee": fee,
    }


async def leave_tournament(tournament_id: str, telegram_id: int) -> Dict:
    tournament = await get_tournament(tournament_id)
    if not tournament or tournament.get("status") != "registration":
        return {"status": "inactive"}
    entry = await _col("tournament_players").find_one_and_delete(
        {"tournament_id": _oid(tournament_id), "telegram_id": telegram_id}
    )
    if not entry:
        return {"status": "not_joined"}
    await _col("tournaments").update_one(
        {"_id": _oid(tournament_id)}, {"$pull": {"players": telegram_id}}
    )
    if entry.get("entry_fee") and not entry.get("refunded"):
        await _col("users").update_one(
            {"telegram_id": telegram_id},
            {"$inc": {"coins": int(entry["entry_fee"])}} ,
        )
    return {"status": "left", "refund": int(entry.get("entry_fee", 0) or 0)}


async def start_tournament(tournament_id: str) -> bool:
    result = await _col("tournaments").update_one(
        {"_id": _oid(tournament_id), "status": "registration"},
        {"$set": {"status": "active", "current_round": 1, "started_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0


async def create_tournament_match(
    tournament_id: str,
    round_no: int,
    match_number: int,
    player1_id: int,
    player2_id: Optional[int],
    status: str = "pending",
    winner_id: Optional[int] = None,
) -> Dict:
    doc = {
        "tournament_id": _oid(tournament_id),
        "round": round_no,
        "match_number": match_number,
        "player1_id": player1_id,
        "player2_id": player2_id,
        "status": status,
        "winner_id": winner_id,
        "room_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    result = await _col("tournament_matches").insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc["tournament_id"] = tournament_id
    return doc


async def get_tournament_matches(tournament_id: str, round_no: Optional[int] = None):
    query = {"tournament_id": _oid(tournament_id)}
    if round_no is not None:
        query["round"] = round_no
    cursor = _col("tournament_matches").find(query).sort(
        [("round", 1), ("match_number", 1)]
    )
    return [_to_dict(doc) async for doc in cursor]


async def get_tournament_match_by_room(room_id: str) -> Optional[Dict]:
    return _to_dict(await _col("tournament_matches").find_one({"room_id": room_id}))


async def activate_tournament_match(match_id: str, room_id: str) -> bool:
    result = await _col("tournament_matches").update_one(
        {"_id": _oid(match_id), "status": "pending", "room_id": None},
        {"$set": {"status": "active", "room_id": room_id}},
    )
    return result.modified_count > 0


async def finish_tournament_match(
    match_id: str, winner_id: int, reason: str = "bingo"
) -> bool:
    result = await _col("tournament_matches").update_one(
        {"_id": _oid(match_id), "status": {"$in": ["pending", "active"]}},
        {"$set": {
            "status": "finished",
            "winner_id": winner_id,
            "finish_reason": reason,
            "finished_at": datetime.now(timezone.utc),
        }},
    )
    return result.modified_count > 0


async def complete_tournament(tournament_id: str, champion_id: int) -> bool:
    result = await _col("tournaments").update_one(
        {"_id": _oid(tournament_id), "status": "active", "prize_paid": False},
        {"$set": {
            "status": "completed",
            "champion": champion_id,
            "completed_at": datetime.now(timezone.utc),
        }},
    )
    if not result.modified_count:
        return False
    amount = int((await get_tournament(tournament_id)).get("prize_coins", 0) or 0)
    if amount:
        await _col("users").update_one(
            {"telegram_id": champion_id}, {"$inc": {"coins": amount}
        })
    await _col("tournaments").update_one(
        {"_id": _oid(tournament_id)}, {"$set": {"prize_paid": True, "payout_coins": amount}}
    )
    return True


async def cancel_tournament(tournament_id: str) -> Dict:
    tournament = await get_tournament(tournament_id)
    if not tournament or tournament.get("status") not in ("registration", "active"):
        return {"status": "inactive", "refunds": 0}
    if tournament.get("status") == "active":
        await _col("rooms").update_many(
            {"tournament_id": tournament_id, "status": {"$in": ["waiting", "playing"]}},
            {"$set": {"status": "cancelled"}},
        )
    entries = await _col("tournament_players").find(
        {"tournament_id": _oid(tournament_id), "refunded": False}
    ).to_list(length=None)
    refunds = 0
    for entry in entries:
        fee = int(entry.get("entry_fee", 0) or 0)
        if fee:
            await _col("users").update_one(
                {"telegram_id": entry["telegram_id"]}, {"$inc": {"coins": fee}}
            )
            refunds += fee
    await _col("tournament_players").update_many(
        {"tournament_id": _oid(tournament_id), "refunded": False},
        {"$set": {"refunded": True}},
    )
    await _col("tournaments").update_one(
        {"_id": _oid(tournament_id)},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)}},
    )
    return {"status": "cancelled", "refunds": refunds, "players": len(entries)}
