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


def _draft(context):
    return context.user_data.setdefault("tournament_draft", {
        "title": "", "prize": "", "max_players": "", "start_at": "", "rules": ""
    })


def _draft_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 Name", callback_data="tcreate:title"),
         InlineKeyboardButton("🎁 Prize", callback_data="tcreate:prize")],
        [InlineKeyboardButton("👥 Maximum Players", callback_data="tcreate:max_players")],
        [InlineKeyboardButton("📅 Date & Time of Match", callback_data="tcreate:start_at")],
        [InlineKeyboardButton("📜 Rules", callback_data="tcreate:rules")],
        [InlineKeyboardButton("👀 Preview", callback_data="tcreate:preview"),
         InlineKeyboardButton("✅ Create Tournament", callback_data="tcreate:create")],
        [InlineKeyboardButton("❌ Cancel", callback_data="tcreate:cancel")],
    ])


def _draft_text(d):
    return (
        "🏆 <b>Tournament Creator</b>\n\n"
        f"🏆 <b>Name:</b> {escape(d.get('title') or 'Not set')}\n"
        f"🎁 <b>Prize:</b> {escape(d.get('prize') or 'Not set')}\n"
        f"👥 <b>Maximum Players:</b> {escape(str(d.get('max_players') or 'Not set'))}\n"
        f"📅 <b>Date & Time:</b> {escape(d.get('start_at') or 'Not set')}\n"
        f"📜 <b>Rules:</b> {escape(d.get('rules') or 'Not set')}\n\n"
        "Tap a button below to enter or change each detail."
    )


async def cmd_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if not _is_owner(user.id):
        await update.message.reply_text("🚫 Only the bot owner can manage tournaments.")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("🔒 Tournament management commands work only in the bot DM.")
        return

    action = args[0].lower() if args else ""
    if action == "create" and len(args) == 1:
        if await _active_tournament():
            await update.message.reply_text("❌ An active tournament already exists. Cancel it first.")
            return
        context.user_data["tournament_draft"] = {"title":"", "prize":"", "max_players":"", "start_at":"", "rules":""}
        context.user_data.pop("tournament_waiting_field", None)
        await update.message.reply_text(_draft_text(_draft(context)), parse_mode="HTML", reply_markup=_draft_keyboard())
        return

    # Backward-compatible direct creation format.
    if action == "create" and len(args) > 1:
        if await _active_tournament():
            await update.message.reply_text("❌ An active tournament already exists. Cancel it first.")
            return
        payload = update.message.text.partition("create")[2].strip()
        parts = [x.strip() for x in payload.split("|")]
        if len(parts) < 5:
            await update.message.reply_text("Use the new creator panel: /tournament create")
            return
        d = {"title":parts[0], "prize":parts[1], "start_at":parts[2], "max_players":parts[3], "rules":parts[4]}
        context.user_data["tournament_draft"] = d
        await _create_from_draft(update, context)
        return

    if not action:
        await update.message.reply_text(
            "🏆 <b>Tournament Control</b>\n\n"
            "/tournament create — open inline tournament creator\n"
            "/tournament info\n/tournament announce\n/tournament start\n/tournament cancel\n"
            "/disqualify @username\n/round", parse_mode="HTML")
        return

    t = await _active_tournament()
    if not t:
        await update.message.reply_text("❌ No active tournament.")
        return
    if action == "info":
        await _send_tournament_info(context.bot, user.id, t)
    elif action in ("announce", "announch"):
        text = (
            f"🏆 <b>{escape(t['title'])}</b> 🏆\n\n"
            f"🎁 <b>PRIZE:</b> {escape(t.get('prize') or 'TBA')}\n"
            f"📅 <b>DATE & TIME:</b> {escape(_fmt_start(t.get('start_at')))}\n"
            f"👥 <b>PLAYERS:</b> {len(t.get('players', []))}/{t.get('max_players') or '∞'}\n\n"
            f"📜 <b>RULES</b>\n{escape(t.get('rules') or 'Single elimination.')}\n\n"
            "Tap the button below to join the tournament."
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏆 Join Tournament", callback_data=f"tjoin:{t['id']}")]])
        await context.bot.send_message(chat_id=t["group_id"], text=text, parse_mode="HTML", reply_markup=keyboard)
        await update.message.reply_text("📢 Tournament announcement sent with the Join Tournament button.")
    elif action == "start":
        await start_tournament(context, t)
        await update.message.reply_text("🚀 Tournament start command processed.")
    elif action == "cancel":
        await db.update_tournament(t["id"], status="cancelled")
        await update.message.reply_text("🛑 Tournament cancelled.")
    else:
        await update.message.reply_text("Unknown action. Use /tournament for the control panel.")


async def _create_from_draft(update, context):
    d = _draft(context)
    missing = [label for key, label in [("title","Name"),("prize","Prize"),("max_players","Maximum Players"),("start_at","Date & Time"),("rules","Rules")] if not str(d.get(key) or '').strip()]
    if missing:
        await update.effective_message.reply_text("❌ Please complete: " + ", ".join(missing))
        return
    try:
        max_players = int(d["max_players"])
        if max_players < 2:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("❌ Maximum players must be a number of at least 2.")
        return
    if not TOURNAMENT_GROUP_ID:
        await update.effective_message.reply_text("❌ TOURNAMENT_GROUP_ID is not configured.")
        return
    t = await db.create_tournament(d["title"], d["prize"], d["start_at"], max_players, d["rules"], TOURNAMENT_GROUP_ID)
    context.user_data.pop("tournament_draft", None)
    context.user_data.pop("tournament_waiting_field", None)
    await update.effective_message.reply_text(f"✅ Tournament created: <b>{escape(t['title'])}</b>\n\nUse /tournament announce to publish it.", parse_mode="HTML")


async def handle_tournament_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    if data.startswith("tcreate:"):
        if not _is_owner(query.from_user.id):
            await query.answer("Only the bot owner can use the tournament creator.", show_alert=True)
            return
        action = data.split(":", 1)[1]
        if action == "cancel":
            context.user_data.pop("tournament_draft", None)
            context.user_data.pop("tournament_waiting_field", None)
            await query.edit_message_text("❌ Tournament creation cancelled.")
            await query.answer()
            return
        if action == "preview":
            d = _draft(context)
            await query.answer()
            await query.message.reply_text(_draft_text(d), parse_mode="HTML")
            return
        if action == "create":
            await query.answer()
            await _create_from_draft(update, context)
            return
        context.user_data["tournament_waiting_field"] = action
        labels = {"title":"tournament name", "prize":"prize", "max_players":"maximum players", "start_at":"date and time of the match", "rules":"rules"}
        await query.answer()
        await query.message.reply_text(f"✍️ Send the <b>{labels[action]}</b> now.", parse_mode="HTML")
        return
    if data.startswith("tjoin:"):
        tid = data.split(":", 1)[1]
        t = await db.get_tournament(tid)
        if not t or t.get("status") != "registration":
            await query.answer("Tournament registration is closed.", show_alert=True)
            return
        uid = query.from_user.id
        if uid in t.get("players", []):
            await query.answer(f"Already joined! {len(t.get('players', []))}/{t.get('max_players') or '∞'}", show_alert=True)
            return
        max_players = t.get("max_players")
        if max_players and len(t.get("players", [])) >= max_players:
            await query.answer("Tournament is full.", show_alert=True)
            return
        await db.create_user(uid, query.from_user.username, query.from_user.first_name)
        ok = await db.add_tournament_player(tid, uid, max_players)
        if not ok:
            await query.answer("Could not join. Please try again.", show_alert=True)
            return
        count = len(t.get("players", [])) + 1
        await query.answer(f"Successfully joined! {count}/{max_players or '∞'}", show_alert=True)
        name = display_name_from_db({"first_name": query.from_user.first_name or "", "username": query.from_user.username or ""})
        username = f"@{query.from_user.username}" if query.from_user.username else "No username"
        try:
            await context.bot.send_message(chat_id=t["group_id"], text=(
                "🎟️ <b>New Tournament Player Joined!</b>\n\n"
                f"👤 <b>Name:</b> {escape(name)}\n"
                f"🔗 <b>Username:</b> {escape(username)}\n"
                f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
                f"👥 <b>Joined:</b> {count}/{max_players or '∞'}"
            ), parse_mode="HTML")
        except Exception:
            pass


async def capture_tournament_creator_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("tournament_waiting_field")
    if not field or not update.message or not update.message.text:
        return
    if update.effective_user.id != OWNER_ID or update.effective_chat.type != "private":
        return
    value = update.message.text.strip()
    if value.startswith("/"):
        return
    _draft(context)[field] = value
    context.user_data.pop("tournament_waiting_field", None)
    await update.message.reply_text("✅ Saved. You can continue editing or preview/create the tournament.", reply_markup=_draft_keyboard())


async def cmd_disqualify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Only the bot owner can disqualify players.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /disqualify @username")
        return
    t = await _active_tournament()
    if not t:
        await update.message.reply_text("❌ No active tournament.")
        return
    if t.get("status") != "registration":
        await update.message.reply_text("❌ Disqualification is available before the tournament starts.")
        return
    raw = context.args[0].strip()
    username = raw[1:] if raw.startswith("@") else raw
    player = await db.find_user_by_username(username)
    if not player:
        await update.message.reply_text("❌ Username not found.")
        return
    if player["telegram_id"] not in t.get("players", []):
        await update.message.reply_text("❌ That user is not registered in this tournament.")
        return
    if not await db.remove_tournament_player(t["id"], player["telegram_id"]):
        await update.message.reply_text("❌ Could not disqualify the player.")
        return
    await update.message.reply_text(f"🚫 Disqualified @{escape(username)} from the tournament.", parse_mode="HTML")


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

    # Odd-player BYEs are eliminated with the configured 5,000 coin reward,
    # so only actual match winners advance to the next round.
    next_players = [m["winner"] for m in current_data.get("matches", []) if m.get("winner")]
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
        # Tournament rule: when a round has an odd number of players, the one
        # unpaired player receives a BYE reward and is eliminated instead of
        # advancing. This prevents an automatic free advancement.
        names = []
        for pid in byes:
            p = await db.get_user(pid)
            name = display_name_from_db(p) if p else str(pid)
            names.append(name)
            await db.add_coins(pid, 5000)
            try:
                await context.bot.send_message(
                    chat_id=pid,
                    text=(
                        f"🎟️ <b>Tournament BYE — Round {round_no}</b>\n\n"
                        f"Because the number of players is odd, you were selected as the unpaired player.\n"
                        f"❌ You are eliminated from this tournament round.\n"
                        f"💰 <b>Compensation:</b> +5,000 Bingo Coins"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await context.bot.send_message(
            chat_id=tournament["group_id"],
            text=(
                f"🎟️ <b>Round {round_no} BYE / Elimination:</b> {escape(', '.join(names))}\n\n"
                f"Because the player count is odd, the unpaired player is removed from the tournament and receives "
                f"💰 <b>5,000 Bingo Coins</b>."
            ),
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
