import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden
import database as db
from models import OWNER_ID

MAX_PLAYERS = 64

def _owner_ok(update):
    return bool(OWNER_ID) and update.effective_user and update.effective_user.id == OWNER_ID

def join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏆 Join Tournament", callback_data="tournament_join")]])

async def cmd_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    source = update.message.reply_to_message
    if not source:
        await update.message.reply_text("Reply to the tournament message with /tournament to create it.")
        return
    await db.create_active_tournament(source.chat_id, source.message_id, MAX_PLAYERS)
    await update.message.reply_text(
        "🏆 Tournament created successfully!\n\nUse /announce to send it to all registered players and groups.\nMaximum players: 64"
    )

async def cmd_announce_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    t = await db.get_active_tournament()
    if not t:
        await update.message.reply_text("❌ No active tournament. Reply to a message with /tournament first.")
        return
    users = await db.get_all_user_ids()
    groups = await db.get_all_group_chat_ids()
    sent = failed = 0
    for chat_id in list(dict.fromkeys(users + groups)):
        try:
            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=t["source_chat_id"],
                message_id=t["source_message_id"],
                reply_markup=join_keyboard(),
            )
            sent += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    await update.message.reply_text(f"📢 Tournament announced!\n✅ Sent: {sent}\n❌ Failed: {failed}")

async def handle_tournament_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    t = await db.get_active_tournament()
    if not t:
        await q.answer("This tournament is no longer active.", show_alert=True)
        return
    result = await db.join_active_tournament(user.id, user.username or "", user.first_name or "", MAX_PLAYERS)
    if result["status"] == "full":
        await q.answer("Tournament is full!", show_alert=True)
        return
    if result["status"] == "already":
        await q.answer(f"You already joined! {result['count']}/64", show_alert=True)
        return
    count = result["count"]
    await q.answer(f"You successfully joined the tournament! {count}/64", show_alert=True)
    owner_text = (
        "🏆 <b>Player Joined Tournament</b>\n\n"
        f"Name: <b>{user.full_name}</b>\n"
        f"Username: @{user.username or 'No username'}\n"
        f"User ID: <code>{user.id}</code>\n"
        f"Number: <b>{count}/64</b>"
    )
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=owner_text, parse_mode="HTML")
    except Exception:
        pass

async def cmd_playerlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    t = await db.get_active_tournament()
    if not t:
        await update.message.reply_text("❌ No active tournament.")
        return
    players = await db.get_tournament_players(t["id"])
    if not players:
        text = "🏆 Tournament Player List\n\nNo players have joined yet. (0/64)"
    else:
        lines = [f"🏆 <b>Tournament Player List ({len(players)}/64)</b>\n"]
        for i,p in enumerate(players,1):
            uname = f"@{p.get('username')}" if p.get('username') else "No username"
            lines.append(f"{i}. <b>{p.get('first_name') or 'Player'}</b> — {uname} — <code>{p['telegram_id']}</code>")
        text = "\n".join(lines)
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=text, parse_mode="HTML")
        if update.effective_chat.id != OWNER_ID:
            await update.message.reply_text("📩 Player list sent to the owner DM.")
    except Exception:
        await update.message.reply_text("❌ Could not send the player list DM.")

async def cmd_cancel_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    await db.cancel_active_tournament()
    await update.message.reply_text("❌ Active tournament cancelled. The player list has been cleared.")
