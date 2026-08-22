import asyncio
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import database as db
from models import OWNER_IDS, TOURNAMENT_GROUP_ID, TOURNAMENT_CHANNEL, OWNER_CONTACT_URL, SUPPORT_CHANNEL
from utils import display_name, display_name_from_db
from cards import build_dm_card_text

TOURNAMENT_LOCKS = defaultdict(asyncio.Lock)
ROUND_LAUNCH_TASKS = {}
WIZARDS: Dict[int, dict] = {}


def _build_bracket_round(players: List[int]):
    """Build a knockout round for any player count (2+).

    We use the next power-of-two bracket size. Players are shuffled first,
    then the missing bracket slots become byes. This keeps the tournament
    flowing cleanly for 3, 5, 6, 10, 12, 20, etc. players.
    Returns (matches, bye_players), where matches are (p1, p2).
    """
    players = list(players)
    if len(players) < 2:
        return [], players
    bracket_size = 1
    while bracket_size < len(players):
        bracket_size *= 2
    bye_count = bracket_size - len(players)
    random.shuffle(players)
    # Randomly select who receives the first-round byes so the same
    # registration order never determines an advantage.
    bye_players = players[:bye_count]
    active = players[bye_count:]
    random.shuffle(active)
    matches = [(active[i], active[i + 1]) for i in range(0, len(active), 2)]
    return matches, bye_players


def _round_summary(count: int) -> str:
    """Human-readable progression for arbitrary tournament sizes."""
    if count < 2:
        return str(count)
    parts = []
    n = count
    while n > 1:
        rooms = n // 2
        if n % 2:
            rooms += 1
        parts.append(f"{n} → {n // 2 + (n % 2)}")
        n = n // 2 + (n % 2)
    return " → ".join(parts) if parts else "1"


def _is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def _esc(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _field_text(t: dict) -> str:
    fee = f"{t.get('entry_fee', 0)}" if t.get('type') == 'paid' else 'Free'
    start = t.get('start_time') or 'Not set'
    return (
        f"🏆 <b>{_esc(t.get('name', 'Tournament'))}</b>\n\n"
        f"💎 Type: <b>{'PAID' if t.get('type') == 'paid' else 'FREE'}</b>\n"
        f"🎁 Prize: <b>{_esc(t.get('prize', 'Not set'))}</b>\n"
        f"👥 Players: <b>{len(t.get('players', []))}/{t.get('max_players', 64)}</b>\n"
        f"💵 Entry: <b>{_esc(str(fee))}</b>\n"
        f"🎁 Odd-player reward: <b>{_esc(str(t.get('paid_bye_reward') or 'Owner provided reward')) if t.get('type') == 'paid' else '10,000 Bingo Coins'}</b>\n"
        f"📜 Rules: {_esc(t.get('rules') or 'Not set')}\n"
        f"⏰ Start: <b>{_esc(start)}</b>\n"
        f"🎁 Odd-player reward: <b>{_esc(t.get('paid_bye_reward') or 'Owner provided reward') if t.get('type') == 'paid' else '10,000 Bingo Coins'}</b>\n"
        f"📍 Venue: <b>Official Bingo Group</b>"
    )


def _wizard_keyboard(t: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 Name: {t.get('name') or 'Set'}", callback_data="tw:name")],
        [InlineKeyboardButton(f"🎁 Prize: {t.get('prize') or 'Set'}", callback_data="tw:prize")],
        [InlineKeyboardButton(f"👥 Players: {t.get('max_players', 64)}", callback_data="tw:max")],
        [InlineKeyboardButton(f"📜 Rules: {'Set' if t.get('rules') else 'Set rules'}", callback_data="tw:rules")],
        [InlineKeyboardButton(f"⏰ Time: {t.get('start_time') or 'Set'}", callback_data="tw:time")],
        [InlineKeyboardButton(f"💵 Cost: {t.get('entry_fee', 0) or 'Set'}", callback_data="tw:fee")],
        [InlineKeyboardButton(f"🎁 Odd Reward: {t.get('paid_bye_reward') or 'Set by owner'}", callback_data="tw:byereward")],
        [InlineKeyboardButton("📣 Create Tournament", callback_data="tw:create"), InlineKeyboardButton("❌ Cancel", callback_data="tw:cancel")],
    ])


async def cmd_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_owner(user.id):
        await update.message.reply_text("❌ Only the tournament owner can create tournaments.")
        return
    WIZARDS[user.id] = {
        'type': None, 'name': '', 'prize': '', 'max_players': 64,
        'rules': '', 'start_time': '', 'entry_fee': 0, 'players': [], 'paid_bye_reward': ''
    }
    await update.message.reply_text(
        "🏆 <b>Create Tournament</b>\n\nFirst choose the tournament type:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🆓 FREE', callback_data='tw:type:free'), InlineKeyboardButton('💰 PAID', callback_data='tw:type:paid')],
            [InlineKeyboardButton('❌ Cancel', callback_data='tw:cancel')]
        ])
    )


async def _wizard_show(query):
    t = WIZARDS.get(query.from_user.id)
    if not t:
        await query.answer('Wizard expired. Use /tournament again.', show_alert=True)
        return
    text = _field_text(t)
    await query.edit_message_text(text + "\n\nSelect a field to edit:", parse_mode='HTML', reply_markup=_wizard_keyboard(t))
    await query.answer()


async def handle_tournament_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    if not _is_owner(uid):
        await q.answer('Owner only.', show_alert=True)
        return
    if data == 'tw:cancel':
        WIZARDS.pop(uid, None)
        await q.edit_message_text('❌ Tournament creation cancelled.')
        await q.answer()
        return
    if data.startswith('tw:type:'):
        t = WIZARDS.get(uid)
        if not t:
            await q.answer('Wizard expired.', show_alert=True); return
        t['type'] = data.rsplit(':', 1)[1]
        await _wizard_show(q); return
    if data.startswith('tw:'):
        t = WIZARDS.get(uid)
        if not t:
            await q.answer('Wizard expired.', show_alert=True); return
        field = data.split(':', 1)[1]
        if field == 'create':
            if t['type'] not in ('free', 'paid'):
                await q.answer('Choose FREE or PAID first.', show_alert=True); return
            if not t['name'] or not t['prize']:
                await q.answer('Set the name and prize first.', show_alert=True); return
            if t['type'] == 'paid' and int(t.get('entry_fee') or 0) <= 0:
                await q.answer('Set the paid entry cost first.', show_alert=True); return
            tid = await db.create_tournament(t, uid)
            WIZARDS.pop(uid, None)
            await q.edit_message_text(
                f"✅ <b>Tournament created!</b>\n\n{_field_text({**t, 'players': []})}\n\n🆔 <code>{tid}</code>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📣 Announce Manually', callback_data=f'tann:{tid}')], [InlineKeyboardButton('▶️ Start Tournament', callback_data=f'tstart:{tid}')]])
            )
            await q.answer('Created.')
            return
        if field in ('name', 'prize', 'max', 'rules', 'time', 'fee', 'byereward'):
            prompts = {
                'name': 'Send the tournament name in your next message.',
                'prize': 'Send the prize exactly as you want it shown (cash, NFT, premium, anything).',
                'max': 'Send the maximum player count (e.g. 64, 32, 16).',
                'rules': 'Send the tournament rules. You can write multiple rules in one message.',
                'time': 'Send the start time/text, e.g. 25 Aug 2026 8:00 PM IST. This is displayed to players.',
                'fee': 'Send the entry cost for the paid tournament (e.g. 100 INR, 5 USDT).',
                'byereward': 'Send exactly what the owner will provide to a player eliminated because the round has an odd number of players (for example: 🎁 Telegram Premium, 🎁 Rose Gift, ₹100 cash, custom gift). The bot only records and announces this description. The bot will NOT send, purchase, transfer, or otherwise provide the reward.',
            }
            t['pending'] = field
            await q.answer()
            await q.message.reply_text(prompts[field])
            return


async def handle_tournament_wizard_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    t = WIZARDS.get(user.id)
    if not t or not t.get('pending') or not update.message or not update.message.text:
        return False
    field = t.pop('pending')
    value = update.message.text.strip()
    if field == 'max':
        try:
            value_int = int(value)
            if value_int < 2 or value_int > 1024:
                raise ValueError
            t['max_players'] = value_int
        except ValueError:
            await update.message.reply_text('❌ Player count must be between 2 and 1024.')
            t['pending'] = 'max'
            return True
    elif field == 'fee':
        t['entry_fee'] = value
    elif field == 'byereward': t['paid_bye_reward'] = value
    elif field == 'name': t['name'] = value
    elif field == 'prize': t['prize'] = value
    elif field == 'rules': t['rules'] = value
    elif field == 'time': t['start_time'] = value
    await update.message.reply_text(_field_text(t), parse_mode='HTML', reply_markup=_wizard_keyboard(t))
    return True


async def _announcement_keyboard(t):
    tid = t['id']
    rows = []
    if t['type'] == 'free':
        rows.append([InlineKeyboardButton('🎮 Join Tournament', callback_data=f'tjoin:{tid}')])
    else:
        contact = OWNER_CONTACT_URL
        rows.append([InlineKeyboardButton('📞 Contact Owner', url=contact)])
    return InlineKeyboardMarkup(rows)


def _announcement_text(t):
    fee = t.get('entry_fee') if t.get('type') == 'paid' else 'FREE'
    return (
        f"🏆 <b>TOURNAMENT ANNOUNCEMENT</b> 🏆\n\n"
        f"🎮 <b>{_esc(t['name'])}</b>\n"
        f"💎 Type: <b>{t['type'].upper()}</b>\n"
        f"🎁 Prize: <b>{_esc(t['prize'])}</b>\n"
        f"👥 Players: <b>{len(t.get('players', []))}/{t['max_players']}</b>\n"
        f"💵 Entry: <b>{_esc(str(fee))}</b>\n"
        f"🎁 Odd-player reward: <b>{_esc(str(t.get('paid_bye_reward') or 'Owner provided reward')) if t.get('type') == 'paid' else '10,000 Bingo Coins'}</b>\n"
        f"📜 Rules: {_esc(t.get('rules') or 'As announced by the owner.')}\n"
        f"⏰ Start: <b>{_esc(t.get('start_time') or 'To be announced')}</b>\n\n"
        f"📍 <b>All tournament games are held in the official Bingo group.</b>"
    )


async def announce_tournament(context: ContextTypes.DEFAULT_TYPE, tid: str) -> tuple[int, int]:
    t = await db.get_tournament(tid)
    if not t:
        return 0, 0
    text = _announcement_text(t)
    kb = await _announcement_keyboard(t)
    sent = failed = 0
    targets = []
    targets.extend(await db.get_all_user_ids())
    targets.extend(await db.get_all_group_ids())
    if TOURNAMENT_CHANNEL:
        targets.append(TOURNAMENT_CHANNEL)
    if TOURNAMENT_GROUP_ID:
        targets.append(TOURNAMENT_GROUP_ID)
    seen = set()
    for target in targets:
        if target in seen: continue
        seen.add(target)
        try:
            await context.bot.send_message(chat_id=target, text=text, parse_mode='HTML', reply_markup=kb)
            sent += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    await db.update_tournament(tid, last_announced_at=datetime.now(timezone.utc))
    return sent, failed


async def cmd_tournamentinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the current/latest tournament details and live status."""
    tid = context.args[0] if context.args else await db.get_latest_tournament_id()
    if not tid:
        await update.message.reply_text("❌ No tournament found.")
        return
    t = await db.get_tournament(tid)
    if not t:
        await update.message.reply_text("❌ Tournament not found.")
        return

    players = list(t.get('players', []))
    status_map = {
        'registration': '📝 Registration Open',
        'ready': '🟡 Ready',
        'running': '🟢 Running',
        'finished': '🏆 Finished',
        'interrupted': '⚠️ Interrupted',
        'cancelled': '❌ Cancelled',
    }
    status = status_map.get(t.get('status'), str(t.get('status', 'Unknown')).title())
    current_round = int(t.get('current_round') or 0)
    progression = t.get('bracket_progression') or _round_summary(len(players))
    winner_id = t.get('winner_id')

    lines = [
        f"🏆 <b>{_esc(t.get('name', 'Tournament'))}</b>",
        "",
        f"📊 Status: <b>{_esc(status)}</b>",
        f"🎮 Type: <b>{'PAID' if t.get('type') == 'paid' else 'FREE'}</b>",
        f"🎁 Prize: <b>{_esc(str(t.get('prize') or 'Not set'))}</b>",
        f"👥 Players: <b>{len(players)}/{t.get('max_players', 0)}</b>",
        f"💵 Entry: <b>{_esc(str(t.get('entry_fee') if t.get('type') == 'paid' else 'FREE'))}</b>",
        f"📜 Rules: {_esc(t.get('rules') or 'As announced by the owner.')}",
        f"⏰ Start: <b>{_esc(str(t.get('start_time') or 'To be announced'))}</b>",
        f"📈 Bracket: <b>{_esc(str(progression or 'Not started'))}</b>",
    ]
    if current_round:
        lines.append(f"🔄 Current Round: <b>{current_round}</b>")
    if t.get('type') == 'paid':
        lines.append(f"🎁 Odd-player reward: <b>{_esc(str(t.get('paid_bye_reward') or 'Owner provided reward'))}</b>")
        lines.append("⚠️ Paid rewards are provided manually by the owner; the bot does not send them.")
    else:
        lines.append("🎁 Odd-player reward: <b>10,000 Bingo Coins</b>")
    if winner_id:
        winner_names = await _players_text(context, [winner_id])
        if winner_names:
            lines.append(f"👑 Champion: <b>{_esc(winner_names[0])}</b>")
    lines.append("📍 Venue: <b>Official Bingo Group</b>")
    lines.append(f"🆔 ID: <code>{_esc(str(tid))}</code>")

    await update.message.reply_text("\n".join(lines), parse_mode='HTML')


async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update.effective_user.id):
        await update.message.reply_text('❌ Owner only.')
        return
    tid = context.args[0] if context.args else await db.get_latest_tournament_id()
    if not tid:
        await update.message.reply_text('❌ No tournament found.')
        return
    sent, failed = await announce_tournament(context, tid)
    await update.message.reply_text(f'📣 Announcement sent.\n✅ Sent: {sent}\n❌ Failed: {failed}')


async def handle_announce_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_owner(q.from_user.id):
        await q.answer('Owner only.', show_alert=True); return
    tid = q.data.split(':', 1)[1]
    sent, failed = await announce_tournament(context, tid)
    await q.answer(f'Sent to {sent} targets; {failed} failed.', show_alert=True)


async def _register_free_tournament_player(context: ContextTypes.DEFAULT_TYPE, tid: str, uid: int, username: str, first_name: str):
    """Register a player in a free tournament and return (ok, message, registration_no, tournament)."""
    t = await db.get_tournament(tid)
    if not t:
        return False, '❌ Tournament ID not found.', None, None
    if t.get('status') != 'registration':
        return False, '❌ Tournament is not accepting registrations.', None, t
    if t.get('type') != 'free':
        return False, '❌ This is a paid tournament. Contact the owner to register.', None, t

    if not await db.get_user(uid):
        await db.create_user(uid, username or '', first_name or '')

    players = list(t.get('players', []))
    if uid in players:
        registration_no = players.index(uid) + 1
        return False, f'ℹ️ You are already registered: {registration_no}/{t.get("max_players", 0)}', registration_no, t
    if len(players) >= int(t.get('max_players', 0)):
        return False, '❌ Tournament is full.', None, t

    registration_no = await db.add_tournament_player(tid, uid)
    if registration_no is None:
        latest = await db.get_tournament(tid)
        current_players = list(latest.get('players', [])) if latest else []
        if uid in current_players:
            registration_no = current_players.index(uid) + 1
            return False, f'ℹ️ You are already registered: {registration_no}/{latest.get("max_players", 0)}', registration_no, latest
        return False, '❌ Registration failed. Please try again.', None, latest

    latest = await db.get_tournament(tid) or t
    return True, f'🎉 Successfully joined!\nRegistration: {registration_no}/{latest.get("max_players", 0)}', registration_no, latest


async def _post_tournament_registration(context: ContextTypes.DEFAULT_TYPE, t: dict, uid: int, username: str, first_name: str, registration_no: int):
    if not TOURNAMENT_CHANNEL:
        return
    total_registered = len(t.get('players', []))
    name = first_name or username or str(uid)
    username_text = f'@{username}' if username else 'No username'
    try:
        await context.bot.send_message(
            TOURNAMENT_CHANNEL,
            f'🎟️ <b>PLAYER REGISTERED</b>\n\n'
            f'🏆 Tournament: <b>{_esc(t.get("name", "Tournament"))}</b>\n'
            f'🔢 Registration No.: <b>{registration_no}/{t.get("max_players", 0)}</b>\n'
            f'👤 Name: <b>{_esc(name)}</b>\n'
            f'🔗 Username: <b>{_esc(username_text)}</b>\n'
            f'🆔 Telegram ID: <code>{uid}</code>\n'
            f'👥 Registered Players: <b>{total_registered}/{t.get("max_players", 0)}</b>',
            parse_mode='HTML',
        )
    except Exception:
        pass


async def cmd_tjoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow players to register for a FREE tournament directly with its tournament ID."""
    if not context.args:
        await update.message.reply_text('Usage: <code>/tjoin TOURNAMENT_ID</code>\n\nExample: <code>/tjoin abc123</code>', parse_mode='HTML')
        return

    tid = context.args[0].strip()
    user = update.effective_user
    ok, message, registration_no, t = await _register_free_tournament_player(
        context, tid, user.id, user.username or '', user.first_name or ''
    )
    await update.message.reply_text(message)
    if ok:
        await _post_tournament_registration(
            context, t, user.id, user.username or '', user.first_name or '', registration_no
        )


async def handle_tournament_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    tid = q.data.split(':', 1)[1]

    ok, message, registration_no, latest = await _register_free_tournament_player(
        context, tid, uid, q.from_user.username or '', q.from_user.first_name or ''
    )
    if not ok:
        await q.answer(message, show_alert=True)
        return

    await q.answer(message, show_alert=True)
    try:
        await q.edit_message_reply_markup(reply_markup=await _announcement_keyboard(latest))
    except Exception:
        pass

    await _post_tournament_registration(
        context, latest, uid, q.from_user.username or '', q.from_user.first_name or '', registration_no
    )


async def cmd_tadd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update.effective_user.id):
        await update.message.reply_text('❌ Owner only.'); return
    if not context.args:
        await update.message.reply_text('Usage: /tadd <user_id> [tournament_id]')
        return
    try: uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text('❌ Use a numeric Telegram user ID.'); return
    tid = context.args[1] if len(context.args) > 1 else await db.get_latest_tournament_id()
    t = await db.get_tournament(tid) if tid else None
    if not t:
        await update.message.reply_text('❌ Tournament not found.'); return
    if t['type'] != 'paid':
        await update.message.reply_text('❌ /tadd is for paid tournaments.'); return
    if not await db.get_user(uid):
        try:
            chat = await context.bot.get_chat(uid)
            await db.create_user(uid, getattr(chat, 'username', '') or '', getattr(chat, 'first_name', '') or '')
        except Exception:
            pass
    if len(t.get('players', [])) >= t['max_players'] and uid not in t.get('players', []):
        await update.message.reply_text('❌ Tournament is full.'); return
    registration_no = await db.add_tournament_player(tid, uid)
    latest = await db.get_tournament(tid) or t
    if registration_no is None:
        players = list(latest.get('players', []))
        registration_no = players.index(uid) + 1 if uid in players else None
        if registration_no is None:
            await update.message.reply_text('❌ Could not register this player.')
            return
        await update.message.reply_text(f'ℹ️ Player is already registered as #{registration_no}.')
    else:
        await update.message.reply_text(
            f'✅ Added <code>{uid}</code> to {t["name"]}.\n🔢 Registration: <b>{registration_no}/{t["max_players"]}</b>',
            parse_mode='HTML',
        )
    try:
        await context.bot.send_message(
            uid,
            f'🏆 You have been registered by the owner for <b>{_esc(t["name"])}</b>.\n'
            f'🔢 Registration: <b>{registration_no}/{t["max_players"]}</b>',
            parse_mode='HTML',
        )
    except Exception:
        pass
    if TOURNAMENT_CHANNEL:
        try:
            chat = await context.bot.get_chat(uid)
            pname = display_name(chat)
            pusername = f'@{chat.username}' if getattr(chat, 'username', None) else 'No username'
            await context.bot.send_message(
                TOURNAMENT_CHANNEL,
                f'🎟️ <b>PLAYER REGISTERED</b>\n\n'
                f'🏆 Tournament: <b>{_esc(t["name"])}</b>\n'
                f'🔢 Registration No.: <b>{registration_no}/{t["max_players"]}</b>\n'
                f'👤 Name: <b>{_esc(pname)}</b>\n'
                f'🔗 Username: <b>{_esc(pusername)}</b>\n'
                f'🆔 Telegram ID: <code>{uid}</code>\n'
                f'👥 Registered Players: <b>{len(latest.get("players", []))}/{t["max_players"]}</b>',
                parse_mode='HTML',
            )
        except Exception:
            pass


async def _players_text(context, ids: List[int]) -> List[str]:
    out=[]
    for uid in ids:
        try:
            u=await context.bot.get_chat(uid)
            out.append(display_name(u))
        except Exception:
            p=await db.get_user(uid)
            out.append(display_name_from_db(p) if p else str(uid))
    return out


async def _start_match(context, tid: str, round_no: int, match: dict):
    """Start one tournament room using the same game flow as normal Bingo.

    Tournament rooms intentionally bypass MAX_ROOMS_PER_CHAT.  The tournament
    launcher is the only limiter and starts rooms with its configured gap.
    """
    room_id = match.get('id')
    room = await db.get_tournament_match(room_id) if room_id else None
    if not room or room.get('p1') is None or room.get('p2') is None:
        if room_id:
            await db.update_tournament_match(room_id, status='invalid')
        return

    p1, p2 = room['p1'], room['p2']
    # Do not send a separate "Starting..." message. The first normal-style
    # match panel is the only live status message for this room.
    await db.update_tournament_match(room_id, status='playing', current_turn=p1, phase='call')

    existing1 = await db.get_tournament_card(room_id, p1)
    existing2 = await db.get_tournament_card(room_id, p2)
    if not existing1:
        await db.create_tournament_card(room_id, p1, random.sample(range(1, 26), 25))
    if not existing2:
        await db.create_tournament_card(room_id, p2, random.sample(range(1, 26), 25))

    # Same as a normal room: private cards + one live group status panel.
    await asyncio.gather(
        _send_tournament_card(context, room_id, p1),
        _send_tournament_card(context, room_id, p2),
        _send_match_panel(context, room_id),
    )


async def _send_match_panel(context, room_id):
    """Send a concise live panel, then delete the previous panel in background."""
    room = await db.get_tournament_match(room_id)
    if not room:
        return
    t = await db.get_tournament(room['tournament_id'])
    p1 = await db.get_user(room['p1'])
    p2 = await db.get_user(room['p2'])
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)

    called = room.get('called_numbers', [])
    called_text = ' • '.join(str(n) for n in called[-12:]) or 'None'
    last = room.get('last_called') or 'None'
    phase = room.get('phase', 'call')
    turn_id = room.get('current_turn')
    turn_name = p1_name if turn_id == room['p1'] else p2_name

    if phase == 'call':
        status = f'🎯 <b>{_esc(turn_name)}</b> — your turn to call.'
    else:
        marker_id = room.get('marker_id')
        marker_name = p1_name if marker_id == room['p1'] else p2_name
        status = f'⚡ <b>{_esc(marker_name)}</b> — mark <b>{last}</b>.'

    text = (
        f'🏆 <b>{_esc(t["name"])}</b> — Match #{room["match_number"]}\n\n'
        f'👤 {p1_name}\n'
        f'👤 {p2_name}\n\n'
        f'📢 Last: <b>{last}</b>\n'
        f'📋 Called: <b>{called_text}</b>\n\n'
        f'{status}'
    )

    rows = [[InlineKeyboardButton('📩 Open My Card', url=f'https://t.me/{context.bot.username}')]]
    # Owner DQ controls remain available but the panel itself stays concise.
    rows.append([
        InlineKeyboardButton('🚫 DQ 1', callback_data=f'tdq:{room_id}:{room["p1"]}'),
        InlineKeyboardButton('🚫 DQ 2', callback_data=f'tdq:{room_id}:{room["p2"]}'),
    ])
    if SUPPORT_CHANNEL:
        rows.append([InlineKeyboardButton('📢 Support Channel', url=SUPPORT_CHANNEL)])

    old_mid = room.get('group_message_id')
    try:
        # Same fast normal-game UX: send newest first, then delete old in the
        # background. Deletion never blocks a number click.
        msg = await context.bot.send_message(
            chat_id=TOURNAMENT_GROUP_ID,
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(rows),
        )
        await db.update_tournament_match(room_id, group_message_id=msg.message_id)
        if old_mid and old_mid != msg.message_id:
            async def _delete_old(mid=old_mid):
                try:
                    await context.bot.delete_message(chat_id=TOURNAMENT_GROUP_ID, message_id=mid)
                except Exception:
                    pass
            asyncio.create_task(_delete_old())
    except Exception:
        pass


def _tournament_card_keyboard(room_id, numbers, marked, last_called, is_my_turn_to_call, need_to_mark):
    rows = []
    marked_set = set(marked or [])
    for r in range(5):
        row = []
        for c in range(5):
            n = numbers[r * 5 + c]
            if n in marked_set:
                label = f'✅{n}'
            elif n == last_called and need_to_mark:
                label = f'⚡{n}'
            else:
                label = str(n)
            row.append(InlineKeyboardButton(label, callback_data=f'tcard:{room_id}:{n}'))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def _send_tournament_card(context, room_id, uid):
    """Use the same detailed private-card layout and update flow as normal Bingo."""
    room = await db.get_tournament_match(room_id)
    card = await db.get_tournament_card(room_id, uid)
    if not room or not card:
        return

    other = room['p2'] if uid == room['p1'] else room['p1']
    me = await db.get_user(uid)
    opponent = await db.get_user(other)
    player_name = display_name_from_db(me)
    opponent_name = display_name_from_db(opponent)
    phase = room.get('phase', 'call')
    marker = room.get('marker_id')
    is_my_turn_to_call = phase == 'call' and room.get('current_turn') == uid
    need_to_mark = phase == 'mark' and marker == uid
    last_called = room.get('last_called')

    text = build_dm_card_text(
        room_number=room.get('match_number', 0),
        player_name=player_name,
        opponent_name=opponent_name,
        numbers=card['numbers'],
        marked=card.get('marked_numbers', []),
        completed_lines=card.get('completed_lines', 0),
        called_numbers=room.get('called_numbers', []),
        is_my_turn_to_call=is_my_turn_to_call,
        need_to_mark=need_to_mark,
        last_called=last_called,
    )
    kb = _tournament_card_keyboard(
        room_id,
        card['numbers'],
        card.get('marked_numbers', []),
        last_called,
        is_my_turn_to_call,
        need_to_mark,
    )

    mid = card.get('card_message_id')
    try:
        if mid:
            await context.bot.edit_message_text(
                chat_id=uid,
                message_id=mid,
                text=text,
                parse_mode='HTML',
                reply_markup=kb,
            )
            return
    except BadRequest as exc:
        if 'Message is not modified' in str(exc):
            return
    except Exception:
        pass

    try:
        msg = await context.bot.send_message(uid, text, parse_mode='HTML', reply_markup=kb)
        await db.update_tournament_card(card['id'], card_message_id=msg.message_id)
    except Exception:
        pass

def _lines(numbers, marked):
    s=set(marked); count=0
    for line in ([0,1,2,3,4],[5,6,7,8,9],[10,11,12,13,14],[15,16,17,18,19],[20,21,22,23,24],[0,5,10,15,20],[1,6,11,16,21],[2,7,12,17,22],[3,8,13,18,23],[4,9,14,19,24],[0,6,12,18,24],[4,8,12,16,20]):
        if all(numbers[i] in s for i in line): count+=1
    return count


async def handle_tournament_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(':')
    if len(parts) != 3:
        await q.answer()
        return
    room_id, n_raw = parts[1], parts[2]
    try:
        n = int(n_raw)
    except ValueError:
        await q.answer('Invalid number.', show_alert=True)
        return
    uid = q.from_user.id
    if q.message.chat.type != 'private':
        await q.answer('Open your private tournament card.', show_alert=True)
        return
    async with TOURNAMENT_LOCKS[room_id]:
        room = await db.get_tournament_match(room_id)
        if not room or room.get('status') != 'playing' or uid not in (room.get('p1'), room.get('p2')):
            await q.answer('Match is not active.', show_alert=True)
            return

        phase = room.get('phase', 'call')
        if phase == 'call':
            if uid != room.get('current_turn'):
                await q.answer('Not your turn.', show_alert=True)
                return
            new_room = await db.claim_tournament_call(room_id, uid, n)
            if not new_room:
                await q.answer('🚫 Number already called or turn changed.', show_alert=True)
                return
            room = new_room
            marker = room.get('marker_id')
            await q.answer(f'📢 Called {n}!')
            # Match the normal-game flow exactly: refresh BOTH private cards
            # immediately after a call.  The caller's card must also refresh,
            # even though only the opponent is the marker for this phase.
            caller = uid
            opponent = room['p1'] if caller == room['p2'] else room['p2']
            await asyncio.gather(
                _send_tournament_card(context, room_id, caller),
                _send_tournament_card(context, room_id, opponent),
                _send_match_panel(context, room_id),
            )
            return

        if phase == 'mark':
            marker = room.get('marker_id')
            last = room.get('last_called')
            if uid != marker or n != last:
                await q.answer(f'You must mark the called number: {last}.', show_alert=True)
                return
            card = await db.get_tournament_card(room_id, uid)
            if not card:
                await q.answer('Card not found.', show_alert=True)
                return
            if n in card.get('marked_numbers', []):
                await q.answer('Already marked.', show_alert=True)
                return
            marked = card.get('marked_numbers', []) + [n]
            lines = _lines(card['numbers'], marked)
            if not await db.claim_tournament_mark(card['id'], n, lines):
                await q.answer('Already marked.', show_alert=True)
                return
            card['marked_numbers'] = list(dict.fromkeys(marked))
            card['completed_lines'] = lines
            if lines >= 5:
                await _finish_match(context, room_id, uid, 'bingo')
                await q.answer('🏆 BINGO!')
                return
            room = await db.transition_tournament_mark_to_call(room_id, uid)
            if not room:
                await q.answer('Match state changed. Try again.', show_alert=True)
                return
            await q.answer(f'✅ Marked {n}!')
            await asyncio.gather(
                _send_tournament_card(context, room_id, uid),
                _send_tournament_card(context, room_id, room['p1'] if uid == room['p2'] else room['p2']),
                _send_match_panel(context, room_id),
            )
            return

    await q.answer()


async def _finish_match(context, room_id, winner_id, reason):
    room=await db.get_tournament_match(room_id)
    if not room or room['status']!='playing': return
    loser=room['p2'] if winner_id==room['p1'] else room['p1']
    await db.update_tournament_match(room_id,status='finished',winner_id=winner_id,loser_id=loser,finish_reason=reason,finished_at=datetime.now(timezone.utc))
    t=await db.get_tournament(room['tournament_id'])
    wp=await db.get_user(winner_id); lp=await db.get_user(loser)
    text=f"🏆 <b>Match #{room['match_number']} finished!</b>\n\n🥇 Winner: <b>{display_name_from_db(wp)}</b>\n😔 Eliminated: <b>{display_name_from_db(lp)}</b>\n\n➡️ Winner advances to the next round."
    try: await context.bot.send_message(TOURNAMENT_GROUP_ID,text,parse_mode='HTML')
    except Exception: pass
    await _maybe_advance_round(context,room['tournament_id'],room['round'])


async def handle_tournament_disqualify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not _is_owner(q.from_user.id): await q.answer('Owner only.',show_alert=True); return
    _,room_id,uid_s=q.data.split(':'); uid=int(uid_s)
    room=await db.get_tournament_match(room_id)
    if not room or room['status']!='playing': await q.answer('Match is not active.',show_alert=True); return
    winner=room['p2'] if uid==room['p1'] else room['p1']
    await _finish_match(context,room_id,winner,'disqualified')
    await q.answer('Player disqualified. Opponent advances.',show_alert=True)


async def _reward_odd_player(context, tid: str, round_no: int, player_id: int):
    """An odd player is NOT a bye-to-next-round. They are eliminated and rewarded."""
    t = await db.get_tournament(tid)
    if not t:
        return
    p = await db.get_user(player_id)
    name = display_name_from_db(p) if p else str(player_id)
    if t.get('type') == 'free':
        await db.add_coins(player_id, 10000)
        reward = '💰 10,000 Bingo Coins'
        try:
            await context.bot.send_message(player_id, '🎁 <b>Tournament consolation reward</b>\n\nYou were selected as the odd player for Round %s and will not play again.\n\n%s have been added to your balance.' % (round_no, reward), parse_mode='HTML')
        except Exception:
            pass
    else:
        reward = t.get('paid_bye_reward') or 'Owner-provided reward'
        try:
            await context.bot.send_message(player_id, '🎁 <b>Tournament consolation reward</b>\n\nYou were selected as the odd player for Round %s and will not play again.\n\nOwner-provided reward: <b>%s</b>\n\n⚠️ The bot does not provide or send this reward. The tournament owner will provide it manually.' % (round_no, _esc(reward)), parse_mode='HTML')
        except Exception:
            pass
        try:
            owner_id = next(iter(OWNER_IDS))
            await context.bot.send_message(owner_id, '🎁 <b>Owner reward required</b>\n\nThe bot will NOT provide or send this reward. Please provide it manually.\n\nTournament: <b>%s</b>\nPlayer: <b>%s</b>\nRound: <b>%s</b>\nReward: <b>%s</b>' % (_esc(t['name']), _esc(name), round_no, _esc(reward)), parse_mode='HTML')
        except Exception:
            pass
    if TOURNAMENT_CHANNEL:
        try:
            await context.bot.send_message(TOURNAMENT_CHANNEL, '🎁 <b>%s</b> was eliminated as the odd player in Round %s and received: <b>%s</b>.' % (_esc(name), round_no, _esc(reward)), parse_mode='HTML')
        except Exception:
            pass

async def _create_round_matches(context, tid, round_no, players):
    random.shuffle(players)
    if len(players) % 2 == 1:
        odd_player = players.pop()
        await db.create_tournament_bye(tid, round_no, odd_player)
        await _reward_odd_player(context, tid, round_no, odd_player)
    for i in range(0, len(players), 2):
        await db.create_tournament_match(tid, round_no, players[i], players[i+1], match_number=(i // 2) + 1, status='pending')

async def _maybe_advance_round(context, tid, round_no):
    matches=await db.get_tournament_matches(tid,round_no)
    if any(m['status'] not in ('finished','bye_rewarded') for m in matches): return
    winners=[m['winner_id'] for m in matches if m.get('status') == 'finished' and m.get('winner_id')]
    all_winners = list(winners)
    t=await db.get_tournament(tid)
    if len(winners)<=1:
        if winners:
            await db.update_tournament(tid,status='finished',winner_id=winners[0])
            p=await db.get_user(winners[0])
            text=f"🏆 <b>TOURNAMENT CHAMPION</b> 🏆\n\n🥇 <b>{display_name_from_db(p)}</b>\n🎁 Prize: <b>{_esc(t['prize'])}</b>"
            await context.bot.send_message(TOURNAMENT_GROUP_ID,text,parse_mode='HTML')
            if TOURNAMENT_CHANNEL:
                try: await context.bot.send_message(TOURNAMENT_CHANNEL,text,parse_mode='HTML')
                except Exception: pass
        return
    next_round=round_no+1
    await db.clear_round_matches(tid,next_round)
    await _create_round_matches(context, tid, next_round, all_winners)
    await db.update_tournament(tid,current_round=next_round)
    if TOURNAMENT_CHANNEL:
        try:
            winner_names = await _players_text(context, all_winners)
            winner_lines = "\n".join(f"🥇 {_esc(name)}" for name in winner_names)
            await context.bot.send_message(
                TOURNAMENT_CHANNEL,
                f"🏆 <b>{_esc(t['name'])}</b> — Round {round_no} winners\n\n{winner_lines}",
                parse_mode='HTML',
            )
        except Exception:
            pass
    await context.bot.send_message(TOURNAMENT_GROUP_ID,f"🔔 <b>Round {next_round} ready!</b>\n\n👥 Advancing players: <b>{len(all_winners)}</b>\n🎯 Odd players are rewarded and eliminated; they do not play again.\n\nStarting rooms with a 10-second gap...",parse_mode='HTML')
    _schedule_round_launch(context, tid, next_round)


async def _launch_round_worker(context, tid, round_no):
    key = (tid, round_no)
    try:
        matches = await db.get_tournament_matches(tid, round_no)
        pending = [m for m in matches if m.get('status') == 'pending']
        # Rooms are intentionally serialized with a 10-second gap to protect
        # Telegram/group responsiveness. The worker itself runs in background
        # so /tstart and round completion never wait for the whole launch queue.
        for index, m in enumerate(pending):
            try:
                await _start_match(context, tid, round_no, m)
            except Exception as exc:
                logging.exception('Failed to start tournament match %s: %s', m.get('id'), exc)
                try:
                    await db.update_tournament_match(m.get('id'), status='pending', launch_error=str(exc)[:500])
                except Exception:
                    pass
            if index < len(pending) - 1:
                await asyncio.sleep(10)

        byes = [m for m in matches if m.get('status') == 'bye']
        for b in byes:
            await db.update_tournament_match(b['id'], status='bye_rewarded')
        if byes:
            await _maybe_advance_round(context, tid, round_no)
    finally:
        ROUND_LAUNCH_TASKS.pop(key, None)

def _schedule_round_launch(context, tid, round_no):
    key = (tid, round_no)
    task = ROUND_LAUNCH_TASKS.get(key)
    if task and not task.done():
        return task
    task = asyncio.create_task(_launch_round_worker(context, tid, round_no))
    ROUND_LAUNCH_TASKS[key] = task
    return task


async def cmd_tstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update.effective_user.id): await update.message.reply_text('❌ Owner only.'); return
    tid=context.args[0] if context.args else await db.get_latest_tournament_id()
    if not tid: await update.message.reply_text('❌ No tournament found.'); return
    ok,msg=await start_tournament(context,tid)
    await update.message.reply_text(msg)


async def start_tournament(context,tid):
    t=await db.get_tournament(tid)
    if not t: return False,'❌ Tournament not found.'
    if not TOURNAMENT_GROUP_ID: return False,'❌ Set TOURNAMENT_GROUP_ID in Heroku Config Vars first.'
    if t['status'] not in ('registration','ready'): return False,f"❌ Tournament status: {t['status']}"
    players=t.get('players',[])
    if len(players)<2: return False,'❌ At least 2 players are required.'
    # Support ANY player count >= 2. For non-power-of-two fields, the bot
    # creates a standard knockout bracket with random odd-player elimination rewards.
    random.shuffle(players)
    await db.clear_tournament_matches(tid)
    round_no=1
    await _create_round_matches(context, tid, round_no, players)
    matches = await db.get_tournament_matches(tid, round_no)
    bye_players = [m['p1'] for m in matches if m.get('status') == 'bye']
    progression = _round_summary(len(players))
    await db.update_tournament(tid,status='running',current_round=round_no,players=players,
                               bracket_size=1 << (len(players)-1).bit_length(),
                               bracket_progression=progression)
    # Do not automatically announce the tournament when it is created or started.
    # The owner controls public registration announcements via /announce.
    _schedule_round_launch(context, tid, round_no)
    return True,'▶️ Tournament started. Rooms are being launched every 10 seconds.'


async def handle_tstart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not _is_owner(q.from_user.id): await q.answer('Owner only.',show_alert=True); return
    tid=q.data.split(':',1)[1]
    ok,msg=await start_tournament(context,tid)
    await q.answer(msg.replace('▶️ ','').replace('❌ ',''),show_alert=True)


async def recover_tournaments(context: ContextTypes.DEFAULT_TYPE):
    # Recover only tournaments that were running when the process restarted.
    running=await db.get_running_tournaments()
    for t in running:
        matches=await db.get_tournament_matches(t['id'],t.get('current_round',1))
        # Unfinished matches are reset to pending; already finished winners stay stored.
        for m in matches:
            if m['status']=='playing': await db.update_tournament_match(m['id'],status='pending')
        _schedule_round_launch(context, t['id'], t.get('current_round', 1))
