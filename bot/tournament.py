"""Persistent knockout tournaments built on the normal Bingo room engine."""
import asyncio
import math
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden
import database as db


def _name(user):
    if not user:
        return "Player"
    return f"@{user['username']}" if user.get("username") else user.get("first_name", "Player")


async def tournament_text(t):
    matches = await db.get_tournament_matches(t["tournament_id"], t.get("current_round") or None)
    names = {p["id"]: _name(await db.get_user(p["id"])) for p in t.get("participants", [])}
    lines = [
        f"🏆 <b>{t['name']}</b>",
        f"👥 Players: {len(t.get('participants', []))}/{t['max_players']}",
        f"💰 Entry: ${t['entry_fee']:,}",
        f"🎁 Prize: ${t['prize']:,}",
        f"📊 Status: {t['status'].replace('_', ' ').title()}",
        f"🎯 Round: {t.get('current_round', 0)}",
    ]
    if matches:
        lines += ["", "<b>MATCHES</b>"]
        for m in matches:
            a, b = names.get(m["player1_id"], "BYE"), names.get(m["player2_id"], "BYE")
            result = f" ✅ {names.get(m.get('winner_id'), 'Winner')}" if m["status"] == "completed" else ""
            lines.append(f"⚔️ {a} vs {b}{result}")
    return "\n".join(lines)


async def cmd_tournament(update, context):
    tournaments = await db.get_tournaments(["registration", "in_progress"], limit=10)
    if not tournaments:
        await update.message.reply_text("🏆 No open tournaments right now.")
        return
    for t in tournaments:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Join", callback_data=f"tj:{t['tournament_id']}"),
            InlineKeyboardButton("📊 Status", callback_data=f"ts:{t['tournament_id']}"),
        ]])
        await update.message.reply_text(await tournament_text(t), parse_mode="HTML", reply_markup=kb)


async def cmd_create(update, context):
    from models import OWNER_ID
    if not OWNER_ID or update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Only the bot owner can create tournaments.")
        return
    raw = " ".join(context.args).split("|")
    if len(raw) < 3:
        await update.message.reply_text(
            "Usage: /createtournament Name | entry_fee | max_players [| prize]\n"
            "Example: /createtournament Sunday Cup | 0 | 8 | 0"
        )
        return
    try:
        name, fee, maximum = raw[0].strip(), max(0, int(raw[1])), int(raw[2])
        prize = int(raw[3]) if len(raw) > 3 else fee * maximum
        if not name or maximum < 2 or maximum > 128 or prize < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Use a valid name, fee, player limit (2–128), and prize.")
        return
    tid = f"VB-{random.randint(100000, 999999)}"
    t = await db.create_tournament(tid, name, update.effective_user.id, fee, maximum,
                                    prize, update.effective_chat.id)
    if not t:
        await update.message.reply_text("❌ That tournament ID already exists. Please try again.")
        return
    await update.message.reply_text(await tournament_text(t), parse_mode="HTML")


async def join_callback(update, context):
    q = update.callback_query
    tid = q.data.split(":", 1)[1]
    t = await db.get_tournament(tid)
    if not t:
        await q.answer("Tournament not found.", show_alert=True); return
    result = await db.join_tournament(tid, q.from_user.id, t["entry_fee"])
    messages = {"joined": "✅ Joined tournament!", "already": "You already joined.",
                "full": "Tournament is full.", "started": "Registration is closed.",
                "insufficient": "You do not have enough Bingo Coins.", "missing": "Tournament not found."}
    await q.answer(messages.get(result, "Could not join."), show_alert=result != "joined")
    if result == "joined":
        updated = await db.get_tournament(tid)
        if len(updated.get("participants", [])) >= updated["max_players"]:
            await start_tournament(tid, context)


async def cmd_join(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /jointournament TOURNAMENT_ID")
        return
    t = await db.get_tournament(context.args[0])
    if not t:
        await update.message.reply_text("❌ Tournament not found."); return
    result = await db.join_tournament(t["tournament_id"], update.effective_user.id, t["entry_fee"])
    await update.message.reply_text({"joined": "✅ You joined!", "already": "You already joined.",
        "full": "❌ Tournament is full.", "started": "❌ Registration is closed.",
        "insufficient": "❌ Not enough Bingo Coins."}.get(result, "❌ Could not join."))
    if result == "joined":
        updated = await db.get_tournament(t["tournament_id"])
        if len(updated.get("participants", [])) >= updated["max_players"]:
            await start_tournament(updated["tournament_id"], context)


async def cmd_leave(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /leavetournament TOURNAMENT_ID"); return
    ok = await db.leave_tournament(context.args[0], update.effective_user.id)
    await update.message.reply_text("✅ Left and received a refund." if ok else "❌ You cannot leave this tournament.")


async def cmd_status(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /tournamentstatus TOURNAMENT_ID"); return
    t = await db.get_tournament(context.args[0])
    await update.message.reply_text(await tournament_text(t), parse_mode="HTML") if t else await update.message.reply_text("❌ Not found.")


async def start_tournament(tid, context):
    t = await db.get_tournament(tid)
    if not t or t["status"] != "registration":
        return
    players = [p["id"] for p in t.get("participants", [])]
    if len(players) < 2:
        return
    random.SystemRandom().shuffle(players)
    size = 1 << math.ceil(math.log2(len(players)))
    players += [None] * (size - len(players))
    await db.set_tournament_started(tid, 1)
    for i in range(0, size, 2):
        a, b = players[i], players[i + 1]
        if a and b:
            await db.create_tournament_match(tid, 1, i // 2, a, b)
        else:
            await db.create_tournament_match(tid, 1, i // 2, a or b, None,
                                              status="completed", winner_id=a or b)
    await advance_round(tid, context, 1)


async def advance_round(tid, context, round_number):
    matches = await db.get_tournament_matches(tid, round_number)
    if not matches or not all(m["status"] == "completed" for m in matches):
        for m in matches:
            if m["status"] == "pending" and m["player2_id"]:
                # Every bracket match must be live at the same time.  Awaiting
                # a five-second countdown here would serialize the round.
                if await db.claim_tournament_match(m["id"]):
                    asyncio.create_task(_launch_match(tid, m, context))
        return
    winners = [m["winner_id"] for m in matches if m.get("winner_id")]
    if len(winners) == 1:
        if await db.award_tournament_prize(tid, winners[0]):
            await _notify(context, (await db.get_tournament(tid))["chat_id"],
                          f"🏆 <b>TOURNAMENT COMPLETED!</b>\n👑 Champion: {_name(await db.get_user(winners[0]))}\n"
                          f"💰 Prize Won: ${ (await db.get_tournament(tid))['prize']:,}")
        return
    next_round = round_number + 1
    for i in range(0, len(winners), 2):
        await db.create_tournament_match(tid, next_round, i // 2, winners[i],
                                          winners[i + 1] if i + 1 < len(winners) else None,
                                          status="pending" if i + 1 < len(winners) else "completed",
                                          winner_id=None if i + 1 < len(winners) else winners[i])
    await db.update_tournament_round(tid, next_round)
    await advance_round(tid, context, next_round)


async def _launch_match(tid, match, context):
    from game import start_game_countdown
    t = await db.get_tournament(tid)
    p1, p2 = await db.get_user(match["player1_id"]), await db.get_user(match["player2_id"])
    placeholder = await context.bot.send_message(t["chat_id"], f"🏆 Tournament match: {_name(p1)} vs {_name(p2)}")
    room_id = await db.create_room(t["chat_id"], match["match_number"] + 1, p1["telegram_id"],
                                   placeholder.message_id, tournament_id=tid,
                                   tournament_match_id=match["id"])
    await db.join_room(room_id, p2["telegram_id"])
    await db.update_tournament_match(match["id"], room_id=room_id)
    await start_game_countdown(context, room_id, t["chat_id"], p1, p2, placeholder.message_id)


async def record_match_result(context, room, winner_id, loser_id):
    """Called by the existing Bingo engine; duplicate callbacks are harmless."""
    if not room.get("tournament_id") or not room.get("tournament_match_id"):
        return
    tid = room["tournament_id"]
    if await db.finish_tournament_match(room["tournament_match_id"], winner_id, loser_id):
        t = await db.get_tournament(tid)
        await db.mark_tournament_eliminated(tid, loser_id)
        consolation = 20000 if t and t["entry_fee"] == 0 else 0
        if consolation:
            await db.add_coins(loser_id, consolation)
        await db._col("users").update_one({"telegram_id": loser_id},
                                          {"$inc": {"tournament_matches_played": 1}})
        await db._col("users").update_one({"telegram_id": winner_id},
                                          {"$inc": {"tournament_matches_played": 1,
                                                    "tournament_matches_won": 1}})
        if consolation:
            await _notify(context, loser_id,
                          "🎁 You were eliminated from the free tournament, but received "
                          "20,000 Bingo Coins as a consolation reward.")
        await advance_round(tid, context, (await db.get_tournament(tid))["current_round"])


async def recover_active_tournaments(context):
    """Reconcile bracket/byes after a deployment restart."""
    for t in await db.get_tournaments(["in_progress"], limit=100):
        await advance_round(t["tournament_id"], context, t.get("current_round", 1))


async def _notify(context, chat_id, text):
    try:
        await context.bot.send_message(chat_id, text, parse_mode="HTML")
    except (Forbidden, BadRequest):
        pass