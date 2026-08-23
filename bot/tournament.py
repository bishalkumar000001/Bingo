import os
import random
from datetime import datetime, timezone
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import database as db
from models import OWNER_ID
from utils import display_name_from_db

TOURNAMENT_GROUP_ID = os.environ.get("TOURNAMENT_GROUP_ID", "").strip()
TOURNAMENT_GROUP_LINK = os.environ.get("TOURNAMENT_GROUP_LINK", "").strip()


def _is_owner(user_id: int) -> bool:
    return OWNER_ID and user_id == OWNER_ID


def _fmt_start(value):
    if not value:
        return "Not specified"
    if isinstance(value, datetime):
        return value.astimezone().strftime("%d %b %Y, %I:%M %p")
    return str(value)


async def _active_tournament():
    return await db.get_active_tournament()


async def _send_tournament_info(bot, chat_id, tournament):
    players = tournament.get("players", [])
    max_players = tournament.get("max_players")
    max_text = str(max_players) if max_players else "Unlimited"
    status = tournament.get("status", "registration")
    current = tournament.get("current_round", 0)
    text = (
        f"🏆 <b>{escape(tournament['title'])}</b>\n\n"
        f"🎁 <b>Prize:</b> {escape(tournament.get('prize') or 'Not announced')}\n"
        f"⏰ <b>Start:</b> {escape(_fmt_start(tournament.get('start_at')))}\n"
        f"👥 <b>Players:</b> {len(players)}/{max_text}\n"
        f"🎯 <b>Status:</b> {status.title()}\n"
        f"🔢 <b>Round:</b> {current or 'Registration'}\n\n"
        f"📜 <b>Rules:</b>\n{escape(tournament.get('rules') or 'Single-elimination Bingo tournament.')}"
    )
    if TOURNAMENT_GROUP_LINK:
        text += f"\n\n📢 <b>Official Group:</b> {escape(TOURNAMENT_GROUP_LINK)}"
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def cmd_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not _is_owner(user.id):
        await update.message.reply_text("🚫 Only the bot owner can manage tournaments.")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("🔒 Tournament management commands work only in the bot DM.")
        return

    if not args:
        t = await _active_tournament()
        if not t:
            await update.message.reply_text(
                "🏆 <b>Tournament Control</b>\n\n"
                "/tournament create Title | Prize | Start time | Max players | Rules\n"
                "/tournament info\n"
                "/tournament announce\n"
                "/tournament start\n"
                "/tournament cancel\n"
                "/round — create the next knockout round after the current round is complete\n\n"
                "Players register with /join.", parse_mode="HTML")
            return
        await _send_tournament_info(context.bot, user.id, t)
        return

    action = args[0].lower()
    if action == "create":
        if await _active_tournament():
            await update.message.reply_text("❌ An active tournament already exists. Cancel it first.")
            return
        payload = update.message.text.partition("create")[2].strip()
        parts = [p.strip() for p in payload.split("|")]
        if len(parts) < 2:
            await update.message.reply_text(
                "Usage:\n/tournament create Title | Prize | Start time | Max players | Rules\n\n"
                "Example:\n/tournament create Velocity Grand Bingo | ₹50,000 Cash + Premium + NFT | 25 Aug 2026 8:00 PM | 64 | Single elimination"
            )
            return
        title = parts[0]
        prize = parts[1]
        start_at = parts[2] if len(parts) > 2 and parts[2] else None
        max_players = None
        if len(parts) > 3 and parts[3]:
            try:
                max_players = int(parts[3])
            except ValueError:
                await update.message.reply_text("❌ Max players must be a number.")
                return
            if max_players < 2:
                await update.message.reply_text("❌ Max players must be at least 2.")
                return
        rules = parts[4] if len(parts) > 4 and parts[4] else "Single-elimination Bingo tournament. Winners advance to the next round."
        if not TOURNAMENT_GROUP_ID:
            await update.message.reply_text("❌ TOURNAMENT_GROUP_ID is not configured.")
            return
        t = await db.create_tournament(
            title=title, prize=prize, start_at=start_at, max_players=max_players,
            rules=rules, group_id=TOURNAMENT_GROUP_ID,
        )
        await update.message.reply_text(
            f"✅ Tournament created: <b>{escape(title)}</b>\n\n"
            f"Players can now join with /join in DM after joining the official group.\n"
            f"Use /tournament announce to publish it.", parse_mode="HTML")
        return

    t = await _active_tournament()
    if not t:
        await update.message.reply_text("❌ No active tournament.")
        return

    if action == "info":
        await _send_tournament_info(context.bot, user.id, t)
    elif action == "announce":
        text = (
            f"🏆 <b>{escape(t['title'])}</b> 🏆\n\n"
            f"🎁 <b>PRIZE:</b> {escape(t.get('prize') or 'TBA')}\n"
            f"⏰ <b>START:</b> {escape(_fmt_start(t.get('start_at')))}\n"
            f"👥 <b>PLAYERS:</b> {len(t.get('players', []))}/{t.get('max_players') or '∞'}\n\n"
            f"📜 <b>RULES</b>\n{escape(t.get('rules') or 'Single elimination.')}\n\n"
            f"1️⃣ Join the official Telegram group.\n"
            f"2️⃣ Open the bot in DM.\n"
            f"3️⃣ Send <code>/join</code>.\n\n"
            f"🎮 The bot automatically shuffles players and creates every 2-player Bingo room."
        )
        if TOURNAMENT_GROUP_LINK:
            text += f"\n\n🔗 {escape(TOURNAMENT_GROUP_LINK)}"
        await context.bot.send_message(chat_id=t["group_id"], text=text, parse_mode="HTML")
        await update.message.reply_text("📢 Tournament announcement sent to the official group.")
    elif action == "start":
        await start_tournament(context, t)
        await update.message.reply_text("🚀 Tournament start command processed.")
    elif action == "cancel":
        await db.update_tournament(t["id"], status="cancelled")
        await update.message.reply_text("🛑 Tournament cancelled.")
    else:
        await update.message.reply_text("Unknown action. Use /tournament for the control panel.")


async def cmd_join_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        await update.message.reply_text("📩 Open the bot in DM and send /join.")
        return
    tournament = await _active_tournament()
    if not tournament or tournament.get("status") != "registration":
        await update.message.reply_text("❌ Tournament registration is not open.")
        return
    if user.id in tournament.get("players", []):
        await update.message.reply_text("✅ You are already registered for this tournament.")
        return

    try:
        member = await context.bot.get_chat_member(tournament["group_id"], user.id)
        if member.status in ("left", "kicked"):
            raise ValueError
    except Exception:
        link = TOURNAMENT_GROUP_LINK or "the official group"
        keyboard = None
        if TOURNAMENT_GROUP_LINK:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Official Group", url=TOURNAMENT_GROUP_LINK)]])
        await update.message.reply_text(
            f"🚫 You must join the official Telegram group first.\n\n🔗 {link}\n\nThen send /join again.",
            reply_markup=keyboard,
        )
        return

    max_players = tournament.get("max_players")
    if max_players and len(tournament.get("players", [])) >= max_players:
        await update.message.reply_text("❌ Tournament is full.")
        return

    await db.create_user(user.id, user.username, user.first_name)
    ok = await db.add_tournament_player(tournament["id"], user.id, max_players)
    if not ok:
        await update.message.reply_text("❌ Registration failed or the tournament just became full.")
        return
    registered_count = len(tournament.get("players", [])) + 1
    await update.message.reply_text(
        f"✅ <b>You are registered!</b>\n\n🏆 {escape(tournament['title'])}\n"
        f"👥 Registered players: {registered_count}/{max_players or '∞'}",
        parse_mode="HTML")

    # Announce every successful registration in the official tournament group.
    player_name = display_name_from_db({
        "first_name": user.first_name or "",
        "username": user.username or "",
    })
    group_name = escape(tournament.get("title") or "Tournament")
    try:
        await context.bot.send_message(
            chat_id=tournament["group_id"],
            text=(
                f"🎟️ <b>New Tournament Player Joined!</b>\n\n"
                f"🏆 <b>{group_name}</b>\n"
                f"👤 <b>{escape(player_name)}</b> has joined the tournament.\n"
                f"👥 <b>Registered:</b> {registered_count}/{max_players or '∞'}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


async def start_tournament(context, tournament):
    if tournament.get("status") != "registration":
        return
    players = list(tournament.get("players", []))
    if len(players) < 2:
        await context.bot.send_message(chat_id=OWNER_ID, text="❌ At least 2 players are required to start.")
        return
    if tournament.get("max_players") and len(players) > tournament["max_players"]:
        return

    for pid in players:
        if await db.is_player_in_active_room(pid):
            await context.bot.send_message(chat_id=OWNER_ID, text=f"❌ Player {pid} is already in an active Bingo room. Finish that game before starting the tournament.")
            return
    await db.update_tournament(tournament["id"], status="active")
    await _create_round(context, tournament["id"], 1, players)


async def cmd_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_owner(user.id):
        await update.message.reply_text("🚫 Only the bot owner can use /round.")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("🔒 Use /round in the bot DM.")
        return
    t = await _active_tournament()
    if not t or t.get("status") != "active":
        await update.message.reply_text("❌ No active tournament is waiting for a round.")
        return
    current = t.get("current_round", 0)
    rounds = t.get("rounds", [])
    if not rounds:
        await update.message.reply_text("❌ Round 1 has not been started. Use /tournament start.")
        return
    current_data = next((r for r in rounds if r["round"] == current), None)
    if not current_data:
        await update.message.reply_text("❌ Current round data is missing.")
        return
    if any(m.get("status") == "playing" for m in current_data.get("matches", [])):
        await update.message.reply_text("⏳ Current round is still running. Wait until every Bingo match has a winner.")
        return
    if any(m.get("winner") is None for m in current_data.get("matches", [])):
        await update.message.reply_text("⏳ Some matches have not finished yet.")
        return

    next_players = [m["winner"] for m in current_data.get("matches", []) if m.get("winner")]
    next_players.extend(current_data.get("byes", []))
    if len(next_players) == 1:
        await _finish_tournament(context, t, next_players[0])
        await update.message.reply_text("🏆 The tournament has a champion!")
        return
    await _create_round(context, t["id"], current + 1, next_players)
    await update.message.reply_text(f"🎮 Round {current + 1} rooms created automatically.")


async def _create_round(context, tournament_id, round_no, players):
    tournament = await db.get_tournament(tournament_id)
    random.shuffle(players)
    byes = []
    if len(players) % 2:
        byes.append(players.pop())

    matches = []
    for index in range(0, len(players), 2):
        p1_id, p2_id = players[index], players[index + 1]
        p1 = await db.get_user(p1_id)
        p2 = await db.get_user(p2_id)
        if not p1 or not p2:
            continue
        placeholder = await context.bot.send_message(
            chat_id=tournament["group_id"],
            text=(f"🏆 <b>{escape(tournament['title'])}</b>\n"
                   f"🎯 <b>Round {round_no}</b> — Match {len(matches) + 1}\n\n"
                   f"👤 {escape(display_name_from_db(p1))}\n"
                   f"⚔️ VS\n"
                   f"👤 {escape(display_name_from_db(p2))}\n\n"
                   f"🎲 Players already joined — starting automatically..."),
            parse_mode="HTML",
        )
        room_id = await db.create_room(
            chat_id=tournament["group_id"],
            room_number=f"T{round_no}-{len(matches) + 1}",
            player1_id=p1_id,
            room_message_id=placeholder.message_id,
        )
        await db.join_room(room_id, p2_id)
        await db.update_room(room_id, tournament_id=tournament_id, tournament_round=round_no, tournament_match=len(matches) + 1)
        matches.append({"room_id": room_id, "player1": p1_id, "player2": p2_id, "winner": None, "status": "playing"})
        from game import start_game_countdown
        asyncio_task = start_game_countdown(context, room_id, tournament["group_id"], p1, p2, placeholder.message_id)
        import asyncio
        asyncio.create_task(asyncio_task)

    await db.append_tournament_round(tournament_id, round_no, matches, byes)
    await db.update_tournament(tournament_id, current_round=round_no)
    if byes:
        names = []
        for pid in byes:
            p = await db.get_user(pid)
            names.append(display_name_from_db(p) if p else str(pid))
        await context.bot.send_message(
            chat_id=tournament["group_id"],
            text=f"🎟️ <b>Round {round_no} BYE:</b> {escape(', '.join(names))}\nThey advance automatically to the next round.",
            parse_mode="HTML",
        )


async def handle_tournament_match_result(context, room, winner_id):
    tournament_id = room.get("tournament_id")
    if not tournament_id:
        return
    t = await db.get_tournament(tournament_id)
    if not t or t.get("status") != "active":
        return
    await db.set_tournament_match_winner(tournament_id, room["id"], winner_id)
    winner = await db.get_user(winner_id)
    if winner:
        await context.bot.send_message(
            chat_id=t["group_id"],
            text=(f"🏆 <b>Tournament Winner — Round {room.get('tournament_round')}</b>\n\n"
                  f"🥇 {escape(display_name_from_db(winner))} advances!\n"
                  f"🎯 Match {room.get('tournament_match')} completed."),
            parse_mode="HTML")


async def _finish_tournament(context, tournament, winner_id):
    await db.update_tournament(tournament["id"], status="finished", champion=winner_id)
    winner = await db.get_user(winner_id)
    name = display_name_from_db(winner) if winner else str(winner_id)
    text = (
        f"👑 <b>TOURNAMENT CHAMPION!</b> 👑\n\n"
        f"🏆 <b>{escape(tournament['title'])}</b>\n"
        f"🥇 Champion: <b>{escape(name)}</b>\n\n"
        f"🎁 <b>Prize:</b> {escape(tournament.get('prize') or 'TBA')}\n\n"
        f"🎉 Congratulations!"
    )
    await context.bot.send_message(chat_id=tournament["group_id"], text=text, parse_mode="HTML")
    try:
        await context.bot.send_message(chat_id=winner_id, text=text, parse_mode="HTML")
    except Exception:
        pass
