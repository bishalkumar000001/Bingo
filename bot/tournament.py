import os
import re
import math
import asyncio
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden

import database as db
from models import OWNER_ID

TOURNAMENT_CHANNEL_ID = os.environ.get("TOURNAMENT_CHANNEL_ID", "")
TOURNAMENT_TZ = os.environ.get("TOURNAMENT_TIMEZONE", "Asia/Kolkata")
TOURNAMENT_GAME_CHAT_ID = os.environ.get("TOURNAMENT_GAME_CHAT_ID", "")


def _owner(user_id: int) -> bool:
    return bool(OWNER_ID) and user_id == OWNER_ID


def _tz():
    try:
        return ZoneInfo(TOURNAMENT_TZ)
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def _parse_dt(value: str):
    value = value.strip()
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_tz()).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _fmt_dt(value):
    if not value:
        return "Not set"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value
    return value.astimezone(_tz()).strftime("%d %b %Y • %I:%M %p") + f" ({TOURNAMENT_TZ})"


def _money(n):
    return f"{int(n):,}"


def _draft_defaults():
    return {
        "name": "Velocity Bingo Tournament",
        "description": "",
        "rules": "",
        "max_players": 32,
        "min_players": 2,
        "entry_fee": 0,
        "prize_1": 20000,
        "prize_2": 0,
        "prize_3": 0,
        "start_at": None,
        "registration_deadline": None,
        "auto_start": True,
        "channel_id": TOURNAMENT_CHANNEL_ID,
        "game_chat_id": TOURNAMENT_GAME_CHAT_ID,
        "timezone": TOURNAMENT_TZ,
        "type": "free",
    }


def _panel(d):
    typ = "Free" if int(d.get("entry_fee", 0)) == 0 else "Paid"
    return (
        "🏆 <b>TOURNAMENT SETUP</b>\n\n"
        f"📛 <b>Name:</b> {escape(str(d.get('name') or 'Not set'))}\n"
        f"🎟 <b>Type:</b> {typ}\n"
        f"👥 <b>Players:</b> {d.get('min_players', 2)}–{d.get('max_players', 32)}\n"
        f"💳 <b>Entry:</b> 🪙 {_money(d.get('entry_fee', 0))}\n"
        f"🥇 <b>1st:</b> 🪙 {_money(d.get('prize_1', 0))}\n"
        f"🥈 <b>2nd:</b> 🪙 {_money(d.get('prize_2', 0))}\n"
        f"🥉 <b>3rd:</b> 🪙 {_money(d.get('prize_3', 0))}\n"
        f"🗓 <b>Start:</b> {_fmt_dt(d.get('start_at'))}\n"
        f"⏳ <b>Registration closes:</b> {_fmt_dt(d.get('registration_deadline'))}\n"
        f"📢 <b>Channel:</b> {escape(str(d.get('channel_id') or 'Not set'))}\n"
        f"🎮 <b>Game Group:</b> {escape(str(d.get('game_chat_id') or 'Not set'))}\n"
        f"⚡ <b>Auto start:</b> {'ON' if d.get('auto_start') else 'OFF'}\n"
    )


def _setup_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📛 Name", callback_data="ts:name"), InlineKeyboardButton("📝 Description", callback_data="ts:description")],
        [InlineKeyboardButton("📜 Rules", callback_data="ts:rules"), InlineKeyboardButton("👥 Players", callback_data="ts:players")],
        [InlineKeyboardButton("💳 Entry Fee", callback_data="ts:entry"), InlineKeyboardButton("🏆 Prizes", callback_data="ts:prizes")],
        [InlineKeyboardButton("🗓 Start Time", callback_data="ts:start"), InlineKeyboardButton("⏳ Reg. Deadline", callback_data="ts:deadline")],
        [InlineKeyboardButton("📢 Channel", callback_data="ts:channel"), InlineKeyboardButton("🎮 Game Group", callback_data="ts:gamechat")],
        [InlineKeyboardButton("⚡ Auto Start", callback_data="ts:auto"), InlineKeyboardButton("🔀 Shuffle & Rooms", callback_data="ts:shuffle")],
        [InlineKeyboardButton("🔄 Free Tournament", callback_data="ts:free"), InlineKeyboardButton("💰 Paid Tournament", callback_data="ts:paid")],
        [InlineKeyboardButton("👁 Preview", callback_data="ts:preview"), InlineKeyboardButton("🚀 CREATE TOURNAMENT", callback_data="ts:create")],
        [InlineKeyboardButton("❌ Cancel Setup", callback_data="ts:cancel")],
    ])


async def cmd_tournament_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only.")
        return
    context.user_data["tournament_draft"] = _draft_defaults()
    context.user_data.pop("tournament_input", None)
    await update.message.reply_text(_panel(context.user_data["tournament_draft"]), parse_mode="HTML", reply_markup=_setup_keyboard())


async def _ask(query, context, field, prompt):
    context.user_data["tournament_input"] = field
    await query.message.reply_text(prompt, parse_mode="HTML")
    await query.answer()


async def tournament_setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _owner(query.from_user.id):
        await query.answer("Owner only.", show_alert=True)
        return
    data = query.data.split(":", 1)[1]
    d = context.user_data.get("tournament_draft")
    if not d:
        await query.answer("Setup expired. Use /tournament_create again.", show_alert=True)
        return
    if data == "name":
        await _ask(query, context, "name", "📛 Send the tournament <b>name</b>.")
    elif data == "description":
        await _ask(query, context, "description", "📝 Send the tournament description. Send <code>-</code> to clear it.")
    elif data == "rules":
        await _ask(query, context, "rules", "📜 Send the tournament rules. Send <code>-</code> to clear them.")
    elif data == "players":
        await _ask(query, context, "players", "👥 Send player limits like <code>32</code> or <code>9 2</code> (max, min). Any max player count is supported.")
    elif data == "entry":
        await _ask(query, context, "entry", "💳 Send entry fee in coins. Use <code>0</code> for free.")
    elif data == "prizes":
        await _ask(query, context, "prizes", "🏆 Send prizes as <code>1st 2nd 3rd</code>, for example <code>100000 50000 25000</code>.")
    elif data == "start":
        await _ask(query, context, "start", f"🗓 Send start time in <code>YYYY-MM-DD HH:MM</code> ({TOURNAMENT_TZ}).")
    elif data == "deadline":
        await _ask(query, context, "deadline", f"⏳ Send registration deadline in <code>YYYY-MM-DD HH:MM</code> ({TOURNAMENT_TZ}), or <code>-</code> for no deadline.")
    elif data == "channel":
        await _ask(query, context, "channel", "📢 Send your channel ID (e.g. <code>-100123...</code>) or public @username. The bot must be able to post there.")
    elif data == "gamechat":
        await _ask(query, context, "gamechat", "🎮 Send the group ID where tournament Bingo rooms should be created (e.g. <code>-100123...</code>). The bot must be admin there.")
    elif data == "shuffle":
        d["shuffle_players"] = not d.get("shuffle_players", True)
        await query.message.edit_text(_panel(d), parse_mode="HTML", reply_markup=_setup_keyboard())
        await query.answer("Shuffle updated")
    elif data == "auto":
        d["auto_start"] = not d.get("auto_start", True)
        await query.message.edit_text(_panel(d), parse_mode="HTML", reply_markup=_setup_keyboard())
        await query.answer("Auto start updated")
    elif data == "free":
        d["entry_fee"] = 0
        d["type"] = "free"
        await query.message.edit_text(_panel(d), parse_mode="HTML", reply_markup=_setup_keyboard())
        await query.answer("Free tournament selected")
    elif data == "paid":
        if d.get("entry_fee", 0) == 0:
            d["entry_fee"] = 1000
        d["type"] = "paid"
        await query.message.edit_text(_panel(d), parse_mode="HTML", reply_markup=_setup_keyboard())
        await query.answer("Paid tournament selected")
    elif data == "preview":
        await query.message.reply_text(_announcement_text(d, preview=True), parse_mode="HTML")
        await query.answer()
    elif data == "create":
        if not d.get("channel_id"):
            await query.answer("Set a channel first.", show_alert=True)
            return
        if not d.get("game_chat_id"):
            await query.answer("Set the tournament game group first.", show_alert=True)
            return
        tid = await db.create_tournament(d)
        await query.message.edit_text(f"✅ <b>Tournament created!</b>\n\n🆔 <code>{tid}</code>\n\nUse /tournament_manage {tid} to manage it.", parse_mode="HTML")
        await publish_tournament(context, tid)
        context.user_data.pop("tournament_draft", None)
        context.user_data.pop("tournament_input", None)
        await query.answer("Created")
    elif data == "cancel":
        context.user_data.pop("tournament_draft", None)
        context.user_data.pop("tournament_input", None)
        await query.message.edit_text("❌ Tournament setup cancelled.")
        await query.answer()


async def handle_tournament_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner(update.effective_user.id):
        return False
    d = context.user_data.get("tournament_draft")
    field = context.user_data.get("tournament_input")
    if not d or not field or not update.message or not update.message.text:
        return False
    value = update.message.text.strip()
    ok = True
    err = None
    if field == "name":
        d["name"] = value[:100]
    elif field in ("description", "rules"):
        d[field] = "" if value == "-" else value[:3000]
    elif field == "players":
        p = value.split()
        try:
            maxp = int(p[0]); minp = int(p[1]) if len(p) > 1 else 2
            if maxp < 2 or minp < 2 or minp > maxp:
                raise ValueError
            d["max_players"], d["min_players"] = maxp, minp
        except ValueError:
            ok = False; err = "Use max or max min, e.g. <code>37</code> or <code>37 9</code>."
    elif field == "gamechat":
        if not value.startswith("-100") and not value.startswith("@"):
            ok = False; err = "Use the numeric group ID like <code>-100123...</code> or a public @username."
        else:
            d["game_chat_id"] = value
    elif field == "entry":
        try:
            n = int(value)
            if n < 0: raise ValueError
            d["entry_fee"] = n; d["type"] = "paid" if n else "free"
        except ValueError:
            ok = False; err = "Entry fee must be a non-negative number."
    elif field == "prizes":
        try:
            vals = [int(x) for x in value.split()]
            if len(vals) != 3 or any(x < 0 for x in vals): raise ValueError
            d["prize_1"], d["prize_2"], d["prize_3"] = vals
        except ValueError:
            ok = False; err = "Send exactly three numbers, e.g. <code>100000 50000 25000</code>."
    elif field in ("start", "deadline"):
        if value == "-" and field == "deadline":
            d["registration_deadline"] = None
        else:
            dt = _parse_dt(value)
            if not dt:
                ok = False; err = f"Invalid date/time. Use <code>YYYY-MM-DD HH:MM</code> in {TOURNAMENT_TZ}."
            else:
                d["start_at" if field == "start" else "registration_deadline"] = dt
    elif field == "channel":
        d["channel_id"] = value
    context.user_data.pop("tournament_input", None)
    if not ok:
        await update.message.reply_text("❌ " + err, parse_mode="HTML")
        return True
    await update.message.reply_text(_panel(d), parse_mode="HTML", reply_markup=_setup_keyboard())
    return True


def _announcement_text(t, preview=False):
    prizes = f"🥇 {_money(t.get('prize_1', 0))} 🪙\n🥈 {_money(t.get('prize_2', 0))} 🪙\n🥉 {_money(t.get('prize_3', 0))} 🪙"
    return (
        f"🏆 <b>{escape(t.get('name','Tournament'))}</b>\n\n"
        f"{escape(t.get('description',''))}\n\n" if t.get('description') else f"🏆 <b>{escape(t.get('name','Tournament'))}</b>\n\n"
    ) + (
        f"👥 Players: <b>{t.get('max_players')}</b> max\n"
        f"🎟 Entry: <b>{_money(t.get('entry_fee',0))} 🪙</b>\n"
        f"🗓 Start: <b>{_fmt_dt(t.get('start_at'))}</b>\n"
        f"⏳ Registration closes: <b>{_fmt_dt(t.get('registration_deadline'))}</b>\n\n"
        f"🏆 <b>PRIZES</b>\n{prizes}\n\n"
        f"📜 <b>RULES</b>\n{escape(t.get('rules','Standard Velocity Bingo tournament rules apply.'))}\n\n"
        f"👇 <b>Press the button below to register.</b>"
    )


def _join_keyboard(tid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎟 REGISTER NOW", callback_data=f"tr:join:{tid}")]])


async def publish_tournament(context, tid):
    t = await db.get_tournament(tid)
    if not t:
        return
    text = _announcement_text(t)
    kb = _join_keyboard(tid)
    results = {"channel": False, "groups_sent": 0, "groups_failed": 0, "users_sent": 0, "users_failed": 0}

    # Primary tournament channel
    try:
        msg = await context.bot.send_message(chat_id=t["channel_id"], text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        await db.update_tournament(tid, announcement_message_id=msg.message_id)
        results["channel"] = True
    except Exception as e:
        await db.update_tournament(tid, publish_error=str(e))

    # Broadcast the same tournament announcement to every known group and every user
    # that the bot has previously seen. Telegram may reject DMs when a user has not
    # started the bot; those failures are counted and do not stop the broadcast.
    for gid in await db.get_all_group_ids():
        if str(gid) == str(t.get("channel_id")):
            continue
        try:
            await context.bot.send_message(chat_id=gid, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            results["groups_sent"] += 1
        except Exception:
            results["groups_failed"] += 1
        await asyncio.sleep(0.05)

    for uid in await db.get_all_user_ids():
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            results["users_sent"] += 1
        except Exception:
            results["users_failed"] += 1
        await asyncio.sleep(0.05)

    await db.update_tournament(tid, broadcast_stats=results)


async def tournament_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = q.data.split(":", 2)[2]
    t = await db.get_tournament(tid)
    if not t:
        await q.answer("Tournament not found.", show_alert=True); return
    now = datetime.now(timezone.utc)
    if t.get("status") != "registration":
        await q.answer("Registration is closed.", show_alert=True); return
    deadline = t.get("registration_deadline")
    if deadline and now >= deadline:
        await q.answer("Registration deadline has passed.", show_alert=True); return
    if await db.tournament_player_exists(tid, q.from_user.id):
        await q.answer("You're already registered!", show_alert=True); return
    count = await db.tournament_player_count(tid)
    if count >= int(t["max_players"]):
        await q.answer("Tournament is full.", show_alert=True); return
    await db.create_user(q.from_user.id, q.from_user.username, q.from_user.first_name)
    await db.add_tournament_player(tid, q.from_user.id, q.from_user.username, q.from_user.first_name)
    count += 1
    uname = f"@{q.from_user.username}" if q.from_user.username else q.from_user.mention_html()
    try:
        await context.bot.send_message(chat_id=t["channel_id"], text=f"✅ <b>Player Registered</b>\n\n👤 {uname}\n🆔 <code>{q.from_user.id}</code>\n🏆 <b>{escape(t['name'])}</b>\n👥 Registered: <b>{count}/{t['max_players']}</b>", parse_mode="HTML")
    except Exception: pass
    await q.answer(f"Registered! {count}/{t['max_players']}", show_alert=True)
    if t.get("auto_start") and count >= int(t.get("max_players", 32)):
        await start_tournament(context, tid)


async def cmd_tournament_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only."); return
    if not context.args:
        await update.message.reply_text("Usage: /tournament_manage <tournament_id>"); return
    t = await db.get_tournament(context.args[0])
    if not t:
        await update.message.reply_text("❌ Tournament not found."); return
    count = await db.tournament_player_count(t["id"])
    await update.message.reply_text(_panel(t) + f"\n👥 <b>Registered:</b> {count}/{t['max_players']}\n🆔 <code>{t['id']}</code>", parse_mode="HTML")


async def cmd_tournament_dq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only."); return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /tournament_dq <tournament_id> <@username|user_id> [reason]"); return
    tid, target = context.args[0], context.args[1]
    reason = " ".join(context.args[2:]) or "Disqualified by tournament admin"
    player = await db.find_user_by_username(target.lstrip("@")) if not target.isdigit() else await db.get_user(int(target))
    if not player:
        await update.message.reply_text("❌ Player not found."); return
    ok = await db.disqualify_tournament_player(tid, player["telegram_id"], reason)
    if not ok:
        await update.message.reply_text("❌ Player is not registered or already disqualified."); return
    t = await db.get_tournament(tid)
    await update.message.reply_text(f"🚫 <b>{escape(player.get('username') or player.get('first_name','Player'))}</b> disqualified.\nReason: {escape(reason)}", parse_mode="HTML")
    if t:
        try:
            await context.bot.send_message(t["channel_id"], f"🚫 <b>Tournament Disqualification</b>\n\n👤 {escape('@'+player['username'] if player.get('username') else player.get('first_name','Player'))}\n📛 Reason: {escape(reason)}\n🏆 {escape(t['name'])}", parse_mode="HTML")
        except Exception: pass
    # A DQ can complete a pending bracket match; advance if the round is now complete.
    for m in await db.get_tournament_matches(tid):
        if m.get("status") == "completed" and m.get("resolution") == "DQ":
            try:
                await advance_tournament(context, tid, int(m.get("round", 1)))
            except Exception:
                pass
            break


async def cmd_tournament_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only."); return
    if not context.args:
        await update.message.reply_text("Usage: /tournament_start <tournament_id>"); return
    ok = await start_tournament(context, context.args[0])
    await update.message.reply_text("✅ Tournament started." if ok else "❌ Could not start tournament. Need at least 2 active players.")


async def start_tournament(context, tid):
    t = await db.get_tournament(tid)
    if not t or t.get("status") not in ("registration", "scheduled"):
        return False
    players = await db.get_tournament_players(tid, active_only=True)
    if len(players) < 2:
        return False
    game_chat_id = t.get("game_chat_id") or TOURNAMENT_GAME_CHAT_ID
    if not game_chat_id:
        return False
    try:
        game_chat_id = int(game_chat_id) if str(game_chat_id).lstrip("-").isdigit() else game_chat_id
    except Exception:
        pass

    # Shuffle the active field so registrations do not determine matchups.
    players = players[:]
    random.SystemRandom().shuffle(players)
    n = len(players)
    bracket_size = 1 << (n - 1).bit_length()
    byes = bracket_size - n

    await db.clear_tournament_matches(tid)
    # Put BYEs into the shuffled field first, then pair everybody into round-one matches.
    seeded = players + [None] * byes
    random.SystemRandom().shuffle(seeded)
    pairs = [(seeded[i], seeded[i + 1]) for i in range(0, len(seeded), 2)]

    await db.update_tournament(tid, status="running", current_round=1, bracket_size=bracket_size, game_chat_id=game_chat_id, started_at=datetime.now(timezone.utc), actual_player_count=n)

    from game import start_game_countdown
    created = 0
    for match_no, (a, b) in enumerate(pairs, 1):
        if a is None and b is None:
            continue
        if b is None:
            match_id = await db.create_tournament_match(tid, 1, match_no, a["telegram_id"], None)
            await db.resolve_tournament_match(match_id, a["telegram_id"], "BYE")
            continue
        match_id = await db.create_tournament_match(tid, 1, match_no, a["telegram_id"], b["telegram_id"])
        p1 = await db.get_user(a["telegram_id"])
        p2 = await db.get_user(b["telegram_id"])
        room_no = await db.get_next_tournament_room_number(game_chat_id)
        room_msg = await context.bot.send_message(
            chat_id=game_chat_id,
            text=(f"🏆 <b>{escape(t['name'])}</b> — Tournament Match #{match_no}\n\n"
                   f"👤 {escape(p1.get('username') and '@'+p1['username'] or p1.get('first_name','Player'))}\n"
                   f"🆚\n"
                   f"👤 {escape(p2.get('username') and '@'+p2['username'] or p2.get('first_name','Player'))}\n\n"
                   f"⏳ Starting automatically…"),
            parse_mode="HTML")
        room_id = await db.create_room(game_chat_id, room_no, a["telegram_id"], room_msg.message_id, tournament_match_id=match_id)
        await db.join_room(room_id, b["telegram_id"])
        await db.attach_tournament_match_room(match_id, room_id)
        created += 1
        asyncio.create_task(start_game_countdown(context, room_id, game_chat_id, p1, p2, room_msg.message_id))

    await announce_round(context, tid, 1)
    # If every match was a BYE (should only happen with one active player, already rejected), advance.
    if created == 0:
        await advance_tournament(context, tid, 1)
    return True

async def announce_round(context, tid, round_no):
    t = await db.get_tournament(tid)
    matches = await db.get_tournament_matches(tid, round_no)
    if not t: return
    lines = [f"⚔️ <b>{escape(t['name'])} — Round {round_no}</b>", ""]
    for i, m in enumerate(matches, 1):
        a = await db.get_user(m["player1_id"]) if m.get("player1_id") else None
        b = await db.get_user(m["player2_id"]) if m.get("player2_id") else None
        an = "BYE" if not a else (f"@{a['username']}" if a.get('username') else a.get('first_name','Player'))
        bn = "BYE" if not b else (f"@{b['username']}" if b.get('username') else b.get('first_name','Player'))
        status = " — COMPLETED" if m.get("status") == "completed" else ""
        lines.append(f"<b>Match {i}</b> — {escape(an)} 🆚 {escape(bn)}{status}")
    try: await context.bot.send_message(t["channel_id"], "\n".join(lines), parse_mode="HTML")
    except Exception: pass


async def cmd_tournament_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only."); return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /tournament_winner <tournament_id> <match_id> <@username|user_id>"); return
    tid, mid, target = context.args[:3]
    player = await db.find_user_by_username(target.lstrip("@")) if not target.isdigit() else await db.get_user(int(target))
    if not player:
        await update.message.reply_text("❌ Player not found."); return
    match = await db.get_tournament_match(mid)
    if not match or match["tournament_id"] != tid:
        await update.message.reply_text("❌ Match not found."); return
    if player["telegram_id"] not in (match.get("player1_id"), match.get("player2_id")):
        await update.message.reply_text("❌ Player is not in this match."); return
    await db.resolve_tournament_match(mid, player["telegram_id"], "WINNER")
    await advance_tournament(context, tid, match["round"])
    await update.message.reply_text("✅ Winner recorded and bracket advanced.")


async def advance_tournament(context, tid, round_no):
    t = await db.get_tournament(tid)
    matches = await db.get_tournament_matches(tid, round_no)
    if not matches or any(m.get("status") != "completed" for m in matches):
        return
    winners = [m.get("winner_id") for m in matches if m.get("winner_id")]
    if len(winners) == 1:
        await db.update_tournament(tid, status="completed", champion_id=winners[0], completed_at=datetime.now(timezone.utc))
        winner = await db.get_user(winners[0])
        prize = int(t.get("prize_1", 0))
        if prize:
            await db.add_coins(winners[0], prize)
        try:
            await context.bot.send_message(
                t["channel_id"],
                f"🏆 <b>{escape(t['name'])} COMPLETE!</b>\n\n"
                f"👑 Champion: <b>{escape('@'+winner['username'] if winner and winner.get('username') else winner.get('first_name','Player'))}</b>\n"
                f"💰 Prize: <b>{_money(prize)} 🪙</b>",
                parse_mode="HTML")
        except Exception:
            pass
        return

    next_round = round_no + 1
    await db.clear_tournament_matches(tid, next_round)
    game_chat_id = t.get("game_chat_id") or TOURNAMENT_GAME_CHAT_ID
    try:
        game_chat_id = int(game_chat_id) if str(game_chat_id).lstrip("-").isdigit() else game_chat_id
    except Exception:
        pass

    from game import start_game_countdown
    real_matches = 0
    for i in range(0, len(winners), 2):
        a = winners[i]
        b = winners[i + 1] if i + 1 < len(winners) else None
        match_no = i // 2 + 1
        match_id = await db.create_tournament_match(tid, next_round, match_no, a, b)
        if b is None:
            await db.resolve_tournament_match(match_id, a, "BYE")
            continue
        real_matches += 1
        p1 = await db.get_user(a)
        p2 = await db.get_user(b)
        room_no = await db.get_next_tournament_room_number(game_chat_id)
        room_msg = await context.bot.send_message(
            chat_id=game_chat_id,
            text=(f"🏆 <b>{escape(t['name'])}</b> — Round {next_round}, Match #{match_no}\n\n"
                   f"👤 {escape(p1.get('username') and '@'+p1['username'] or p1.get('first_name','Player'))}\n"
                   f"🆚\n"
                   f"👤 {escape(p2.get('username') and '@'+p2['username'] or p2.get('first_name','Player'))}\n\n"
                   f"⏳ Starting automatically…"),
            parse_mode="HTML")
        room_id = await db.create_room(game_chat_id, room_no, a, room_msg.message_id, tournament_match_id=match_id)
        await db.join_room(room_id, b)
        await db.attach_tournament_match_room(match_id, room_id)
        asyncio.create_task(start_game_countdown(context, room_id, game_chat_id, p1, p2, room_msg.message_id))

    await db.update_tournament(tid, current_round=next_round)
    await announce_round(context, tid, next_round)
    if real_matches == 0:
        await advance_tournament(context, tid, next_round)

