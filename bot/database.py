import aiosqlite
import json
import os
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "velocity_bingo.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                coins INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER,
                status TEXT DEFAULT 'waiting',
                current_turn INTEGER,
                phase TEXT DEFAULT 'call',
                last_called_number INTEGER,
                called_numbers TEXT DEFAULT '[]',
                live_message_id INTEGER,
                room_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                numbers TEXT NOT NULL,
                marked_numbers TEXT DEFAULT '[]',
                completed_lines INTEGER DEFAULT 0,
                card_message_id INTEGER
            )
        """)
        await db.commit()


async def get_user(telegram_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_user(telegram_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (telegram_id, username, first_name)
               VALUES (?, ?, ?)""",
            (telegram_id, username or "", first_name or ""),
        )
        await db.execute(
            """UPDATE users SET username=?, first_name=? WHERE telegram_id=?""",
            (username or "", first_name or "", telegram_id),
        )
        await db.commit()


async def get_active_rooms_in_chat(chat_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rooms WHERE chat_id=? AND status IN ('waiting','playing') ORDER BY room_number",
            (chat_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_next_room_number(chat_id: int) -> int:
    active = await get_active_rooms_in_chat(chat_id)
    used = {r["room_number"] for r in active}
    for n in range(1, 4):
        if n not in used:
            return n
    return -1


async def is_player_in_active_room(player_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id FROM rooms WHERE status IN ('waiting','playing')
               AND (player1_id=? OR player2_id=?)""",
            (player_id, player_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def create_room(
    chat_id: int, room_number: int, player1_id: int, room_message_id: int
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO rooms (room_number, chat_id, player1_id, room_message_id)
               VALUES (?, ?, ?, ?)""",
            (room_number, chat_id, player1_id, room_message_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_room(room_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rooms WHERE id=?", (room_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_room_by_chat_and_number(chat_id: int, room_number: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rooms WHERE chat_id=? AND room_number=? AND status IN ('waiting','playing')",
            (chat_id, room_number),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_room(room_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [room_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE rooms SET {fields} WHERE id=?", values)
        await db.commit()


async def join_room(room_id: int, player2_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rooms SET player2_id=?, status='playing' WHERE id=? AND status='waiting'",
            (player2_id, room_id),
        )
        await db.commit()
    return True


async def create_card(room_id: int, player_id: int, numbers: List[int]) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO cards (room_id, player_id, numbers) VALUES (?, ?, ?)",
            (room_id, player_id, json.dumps(numbers)),
        )
        await db.commit()
        return cursor.lastrowid


async def get_card(room_id: int, player_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cards WHERE room_id=? AND player_id=?",
            (room_id, player_id),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["numbers"] = json.loads(d["numbers"])
            d["marked_numbers"] = json.loads(d["marked_numbers"])
            return d


async def mark_number(card_id: int, number: int, new_lines: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT marked_numbers FROM cards WHERE id=?", (card_id,)
        ) as cursor:
            row = await cursor.fetchone()
        marked = json.loads(row["marked_numbers"])
        if number not in marked:
            marked.append(number)
        await db.execute(
            "UPDATE cards SET marked_numbers=?, completed_lines=? WHERE id=?",
            (json.dumps(marked), new_lines, card_id),
        )
        await db.commit()


async def update_card_message_id(card_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE cards SET card_message_id=? WHERE id=?", (message_id, card_id)
        )
        await db.commit()


async def get_leaderboard(limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT telegram_id, username, first_name, wins, coins, games_played,
                      win_rate, longest_streak
               FROM (
                   SELECT *, CASE WHEN games_played > 0
                       THEN CAST(wins AS REAL)/games_played*100
                       ELSE 0 END AS win_rate
                   FROM users
               )
               WHERE games_played > 0
               ORDER BY wins DESC, coins DESC
               LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def update_user_stats(
    telegram_id: int, won: bool, coins_delta: int
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT wins, losses, current_streak, longest_streak, coins, games_played FROM users WHERE telegram_id=?",
            (telegram_id,),
        ) as cursor:
            row = dict(await cursor.fetchone())

        games_played = row["games_played"] + 1
        wins = row["wins"] + (1 if won else 0)
        losses = row["losses"] + (0 if won else 1)
        coins = max(0, row["coins"] + coins_delta)

        if won:
            current_streak = row["current_streak"] + 1
        else:
            current_streak = 0
        longest_streak = max(row["longest_streak"], current_streak)

        await db.execute(
            """UPDATE users SET games_played=?, wins=?, losses=?, coins=?,
               current_streak=?, longest_streak=? WHERE telegram_id=?""",
            (games_played, wins, losses, coins, current_streak, longest_streak, telegram_id),
        )
        await db.commit()


async def cancel_room(room_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rooms SET status='cancelled' WHERE id=?", (room_id,)
        )
        await db.commit()


async def finish_room(room_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rooms SET status='finished' WHERE id=?", (room_id,)
        )
        await db.commit()


async def get_player_active_room(player_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM rooms WHERE status IN ('waiting','playing')
               AND (player1_id=? OR player2_id=?) LIMIT 1""",
            (player_id, player_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
