import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest, Forbidden
from webserver import start_webserver

import database as db
from rooms import cmd_bingo, handle_join_callback, handle_cancel_room_callback, cmd_stopbingo
from game import (
    handle_card_callback,
    handle_rematch_callback,
    handle_cancel_game_callback,
    handle_forfeit_ask_callback,
    handle_forfeit_confirm_callback,
    _try_unpin,
    _log,
)
from economy import award_winner, record_loss, process_forfeit
from leaderboard import build_leaderboard_text, build_leaderboard_keyboard
from utils import display_name_from_db, display_name
from models import LINES_TO_WIN, WIN_COINS, FORFEIT_COST, CANCEL_FREE_THRESHOLD, OWNER_ID, OWNER_IDS, LOGGER_GROUP_ID, SUPPORT_CHANNEL
from tournament import (
    cmd_tournament_create, cmd_tournament_manage, cmd_tournament_dq, cmd_tournament_start,
    cmd_tournament_winner, tournament_setup_callback, tournament_join_callback,
    handle_tournament_input,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _build_start_text(user):
    return f"""
🎮 <b>VELOCITY BINGO</b>

{user.mention_html()} Welcome to Velocity Bingo! 🔥
Velocity Bingo is a competitive 1v1 Bingo game where two players battle against each other to complete their Bingo cards. Every match is played directly through Telegram with interactive buttons.

🎯 <b>HOW THE GAME WORKS</b>
Each player receives their own private 5×5 Bingo card containing numbers from 1 to 25. Your card is private, so your opponent cannot see which numbers you have available.

⚔️ <b>STARTING A MATCH</b>
Add the bot to your group and use /bingo to create a new game room. Another player can join the room using the Join button, and once both players are ready, the match begins.

🔢 <b>CALLING NUMBERS</b>
Players take turns calling numbers during the match. When a number is called, the opponent checks their private card and can mark that number if it is available on their card.

🎴 <b>YOUR PRIVATE CARD</b>
Your Bingo card is sent to you privately by the bot. The card contains interactive buttons, allowing you to easily select and mark the numbers during the match.

🏆 <b>HOW TO WIN</b>
Your objective is to complete 5 Bingo lines before your opponent. Lines can be completed horizontally, vertically, or diagonally across your 5×5 card.

⚡ <b>STRATEGY</b>
Calling the right numbers at the right time can make a big difference. Watch your progress carefully and try to prevent your opponent from completing their lines before you do.

💰 <b>COINS &amp; REWARDS</b>
Winning a match rewards you with 500 🪙 coins. Your coins can be used as part of the bot's economy, while your match results are saved to your player statistics.

📊 <b>PLAYER STATISTICS</b>
Every match contributes to your gaming statistics. Your wins, losses, streaks and other available statistics can be checked from your profile.

❌ <b>LEAVING A GAME</b>
If you no longer want to continue an active match, you can use the available cancel/forfeit option. Be careful, because leaving a match may affect the result and your rewards.

💡 <b>QUICK TIP</b>
Keep your private Bingo card open while playing. Your opponent's moves and your available number buttons will be shown there, making it easier to follow the match.

🎮 <b>READY TO PLAY?</b>
Add the bot to your group, use /bingo, invite another player and start your battle!
🏆 Complete your 5 lines.
🔥 Beat your opponent.
💰 Earn your reward.
👑 Become the Bingo Champion!
""".strip()


async def _build_start_keyboard(context):
    me = await context.bot.get_me()
    add_url = f"https://t.me/{me.username}?startgroup=true"
    support_url = SUPPORT_CHANNEL or "https://t.me/"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD ME TO GROUP", url=add_url)],
        [InlineKeyboardButton("📢 SUPPORT & UPDATES", url=support_url)],
        [InlineKeyboardButton("❓ HELP / HOW TO PLAY", callback_data="start_help")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username, user.first_name)

    text = await _build_start_text(user)
    keyboard = await _build_start_keyboard(context)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await db.get_user(user.id):
        await db.create_user(user.id, user.username, user.first_name)

    text = f"""
❓ <b>VELOCITY BINGO — HELP</b>

🎮 <b>ABOUT THE GAME</b>
Velocity Bingo is a competitive 1v1 Bingo game where two players compete using private 5×5 cards. Your goal is to complete 5 Bingo lines before your opponent.

⚔️ <b>STARTING A GAME</b>
Use /bingo in a group to create a game room. Another player can join using the Join button. Both players should start the bot privately before playing.

🎴 <b>BINGO CARD</b>
Each player receives a private 5×5 card containing numbers from 1 to 25. Your card uses interactive buttons for selecting and marking numbers.

🔢 <b>GAMEPLAY</b>
Players take turns calling numbers. When a called number is available on your card, use its button to mark it and increase your Bingo progress.

🏆 <b>HOW TO WIN</b>
The first player to complete 5 Bingo lines wins the match. Lines can be completed horizontally, vertically, or diagonally.

💰 <b>REWARDS</b>
Winning a match rewards you with 500 🪙 coins. Your wins, losses, streak and other game statistics are saved automatically.

📋 <b>COMMANDS</b>
🎮 /bingo — Create a new match
👤 /profile — View your profile and statistics
🏆 /leaderboard — View the top players
🎁 /give — Transfer coins to another player
❓ /help — Open this game guide
🛑 /stopbingo — Stop active rooms (Admin)
❌ /cancel — Cancel or forfeit your current game

📌 <b>IMPORTANT</b>
Start the bot privately with /start before playing. This allows the bot to send your private Bingo card and game controls.

💡 <b>QUICK TIP</b>
Keep your private Bingo card open while playing so you can quickly mark numbers and follow your progress.

🔥 Good luck and become the Bingo Champion! 🏆
""".strip()
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    player = await db.get_user(user.id)
    if not player:
        await update.message.reply_text(
            "❌ You're not registered yet! Send /start first."
        )
        return

    name = display_name_from_db(player)
    games = player["games_played"]
    wins = player["wins"]
    losses = player["losses"]
    win_rate = (wins / games * 100) if games > 0 else 0.0
    streak = player["current_streak"]
    longest = player["longest_streak"]
    coins = player["coins"]

    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Profile — {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Coins: <b>{coins:,}</b>\n"
        f"🎮 Games Played: <b>{games}</b>\n"
        f"🏆 Wins: <b>{wins}</b>\n"
        f"😔 Losses: <b>{losses}</b>\n"
        f"📈 Win Rate: <b>{win_rate:.1f}%</b>\n"
        f"🔥 Current Streak: <b>{streak}</b>\n"
        f"⭐ Longest Streak: <b>{longest}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
    )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    is_group = chat.type in ("group", "supergroup")
    chat_id = chat.id if is_group else 0
    scope = "chat" if is_group else "global"
    time_filter = "all_time"

    chat_title = chat.title if is_group else ""
    text = await build_leaderboard_text(scope, time_filter, chat_id, chat_title)
    keyboard = build_leaderboard_keyboard(scope, time_filter, chat_id)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def handle_leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "lb_nochat":
        await query.answer(
            "Current Chat leaderboard is only available in group chats!", show_alert=True
        )
        return

    parts = data.split(":")
    if len(parts) < 4:
        await query.answer()
        return

    scope = parts[1]
    time_filter = parts[2]
    chat_id = int(parts[3])

    chat_title = ""
    if scope == "chat" and chat_id:
        try:
            chat_info = await context.bot.get_chat(chat_id)
            chat_title = chat_info.title or ""
        except Exception:
            pass

    text = await build_leaderboard_text(scope, time_filter, chat_id, chat_title)
    keyboard = build_leaderboard_keyboard(scope, time_filter, chat_id)

    try:
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except BadRequest:
        pass
    await query.answer()


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cancel command — respects the new cancellation rules:
    • Waiting room   → always free, no coins involved.
    • Playing, ≤ CANCEL_FREE_THRESHOLD numbers called
                     → free cancel, no winner, no coins.
    • Playing, > CANCEL_FREE_THRESHOLD numbers called
                     → forfeit: FORFEIT_COST deducted from the caller,
                        opponent receives nothing, match is not counted.
    """
    user = update.effective_user

    player = await db.get_user(user.id)
    if not player:
        await update.message.reply_text("❌ You're not registered. Send /start first.")
        return

    room = await db.get_player_active_room(user.id)
    if not room:
        await update.message.reply_text("❌ You are not in any active game right now.")
        return

    forfeiter_name = display_name_from_db(player)

    # ── Waiting room (no game started yet) ────────────────────────────────
    if room["status"] == "waiting":
        await db.cancel_room(room["id"])
        try:
            await context.bot.edit_message_text(
                chat_id=room["chat_id"],
                message_id=room["room_message_id"],
                text=f"❌ <b>Room #{room['room_number']}</b> was cancelled by {forfeiter_name}.",
                parse_mode="HTML",
            )
        except (BadRequest, KeyError):
            pass
        await update.message.reply_text(
            f"✅ Your waiting room <b>#{room['room_number']}</b> has been cancelled.",
            parse_mode="HTML",
        )
        return

    # ── Game in progress ──────────────────────────────────────────────────
    called = room.get("called_numbers") or []
    chat_id = room["chat_id"]
    opponent_id = (
        room["player2_id"] if user.id == room["player1_id"] else room["player1_id"]
    )
    opponent = await db.get_user(opponent_id)
    opponent_name = display_name_from_db(opponent) if opponent else "Opponent"

    if len(called) <= CANCEL_FREE_THRESHOLD:
        # ── Free cancel (1–5 numbers called) ──────────────────────────────
        await db.cancel_room(room["id"])
        for mid_key in ("live_message_id", "last_call_message_id", "group_panel_message_id"):
            mid = room.get(mid_key)
            if mid:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass

        cancel_text = (
            f"🚫 <b>Match Cancelled — Room #{room['room_number']}</b>\n\n"
            f"<b>{forfeiter_name}</b> cancelled the game.\n"
            f"• No winner declared\n"
            f"• No coins awarded\n"
            f"• Match does not count toward any leaderboard or event"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=cancel_text, parse_mode="HTML")
        except Exception:
            pass
     
    else:
        # ── Paid forfeit (6+ numbers called) ──────────────────────────────
        # Check balance first (non-deducting read — the atomic deduct happens in process_forfeit)
        if player.get("coins", 0) < FORFEIT_COST:
            await update.message.reply_text(
                f"❌ You need at least <b>{FORFEIT_COST} coins</b> to forfeit this match.\n"
                f"Your balance: <b>{player.get('coins', 0)} coins</b>",
                parse_mode="HTML",
            )
            return
        success = await process_forfeit(user.id, chat_id)
        if not success:
            # Race: balance dropped between the check and the atomic deduct
            await update.message.reply_text(
                f"❌ You need at least <b>{FORFEIT_COST} coins</b> to forfeit this match.",
                parse_mode="HTML",
            )
            return
        await db.cancel_room(room["id"])
        for mid_key in ("live_message_id", "last_call_message_id", "group_panel_message_id"):
            mid = room.get(mid_key)
            if mid:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        forfeit_text = (
            f"🏳️ <b>Forfeit — Room #{room['room_number']}</b>\n\n"
            f"😔 <b>{forfeiter_name}</b> forfeited the match.\n"
            f"💸 <b>−{FORFEIT_COST} coins</b> deducted from {forfeiter_name}'s balance.\n"
            f"🤝 No coins awarded to either player.\n"
            f"📊 This match does not count toward event progress or leaderboards."
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=forfeit_text, parse_mode="HTML")
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=opponent_id,
                text=(
                    f"🏳️ <b>{forfeiter_name}</b> forfeited Room #{room['room_number']}.\n"
                    f"You were not awarded any coins (match ended by forfeit)."
                ),
                parse_mode="HTML",
            )
        except (Forbidden, BadRequest):
            pass
        await update.message.reply_text(
            f"🏳️ You forfeited Room <b>#{room['room_number']}</b>.\n"
            f"💸 <b>−{FORFEIT_COST} coins</b> deducted from your balance.",
            parse_mode="HTML",
        )

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not OWNER_IDS or user.id not in OWNER_IDS:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    source = update.message.reply_to_message
    if not source and not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "• Reply to a message with /broadcast to forward it to all users\n"
            "• /broadcast <text> to send a plain message"
        )
        return

    user_ids = await db.get_all_user_ids()
    sent = failed = 0

    status_msg = await update.message.reply_text(
        f"📡 Broadcasting to <b>{len(user_ids)}</b> users...", parse_mode="HTML"
    )

    for uid in user_ids:
        try:
            if source:
                await source.copy(chat_id=uid)
            else:
                await context.bot.send_message(
                    chat_id=uid,
                    text=" ".join(context.args),
                    parse_mode="HTML",
                )
            sent += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    try:
        await status_msg.edit_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Broadcast Complete!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📨 Sent: <b>{sent}</b>\n"
            f"❌ Failed: <b>{failed}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
        )
    except BadRequest:
        pass


async def cmd_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check if user is registered
    sender = await db.get_user(user.id)
    if not sender:
        await update.message.reply_text("❌ You're not registered yet! Send /start first.")
        return
    
    # Parse arguments: /give @username amount or /give user_id amount
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/give @username <amount>\n"
            "/give <user_id> <amount>\n\n"
            f"Your coins: 💰 <b>{sender['coins']:,}</b>",
            parse_mode="HTML",
        )
        return
    
    recipient_input = context.args[0]
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number!")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Amount must be greater than 0!")
        return
    
    if user.id not in OWNER_IDS and sender["coins"] < amount:
        await update.message.reply_text(
            f"❌ You don't have enough coins!\n"
            f"You have: 💰 <b>{sender['coins']:,}</b>\n"
            f"Trying to give: 💰 <b>{amount:,}</b>",
            parse_mode="HTML",
        )
        return
    
    # Try to find recipient
    recipient = None
    
    # If input looks like a user ID (digits)
    if recipient_input.isdigit():
        recipient_id = int(recipient_input)
        recipient = await db.get_user(recipient_id)
    # If input is a username
    elif recipient_input.startswith("@"):
        username = recipient_input[1:]
        # Search for user with this username
        # We need to add this to the database
        cursor = await db.find_user_by_username(username)
        if cursor:
            recipient = cursor
    
    if not recipient:
        await update.message.reply_text("❌ Recipient not found! Use @username or user_id")
        return
    
    if recipient["telegram_id"] == user.id:
        await update.message.reply_text("❌ You can't give coins to yourself!")
        return
    
    # Transfer coins
    if user.id in OWNER_IDS:
        success = await db.add_coins(
            recipient["telegram_id"],
            amount
        )
    else:
        success = await db.transfer_coins(
            user.id,
            recipient["telegram_id"],
            amount
        )
    
    if not success:
        await update.message.reply_text("❌ Transfer failed!")
        return
    
    recipient_name = display_name_from_db(recipient)
    
    await update.message.reply_text(
        f"✅ Transfer successful!\n\n"
        f"Sent: 💰 <b>{amount:,}</b> coins\n"
        f"To: <b>{recipient_name}</b>",
        parse_mode="HTML",
    )
    
    try:
        sender_name = display_name_from_db(sender)
        await context.bot.send_message(
            chat_id=recipient["telegram_id"],
            text=f"🎁 <b>{sender_name}</b> sent you 💰 <b>{amount:,}</b> coins!",
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        pass


async def register_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    try:
        await db.register_group(chat.id, chat.title or "", chat.username or "")
    except Exception:
        pass


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not LOGGER_GROUP_ID:
        return

    result = update.my_chat_member
    if not result:
        return

    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status

    if new_status not in ("member", "administrator"):
        return
    if old_status in ("member", "administrator"):
        return

    chat = result.chat
    if chat.type not in ("group", "supergroup"):
        return
    try:
        await db.register_group(chat.id, chat.title or "", chat.username or "")
    except Exception:
        pass

    added_by = result.from_user
    added_by_name = display_name(added_by) if added_by else "Unknown"

    try:
        member_count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        member_count = "?"

    username_str = f"@{chat.username}" if chat.username else "PRIVATE GROUP"

    try:
        invite_link = await context.bot.export_chat_invite_link(chat.id)
    except Exception:
        invite_link = "❌ NO INVITE PERMISSION"

    log_text = (
        f"📋 <b>CHAT NAME:</b> {chat.title}\n"
        f"🆔 <b>CHAT ID:</b> <code>{chat.id}</code>\n"
        f"👤 <b>CHAT USERNAME:</b> {username_str}\n"
        f"🔗 <b>CHAT LINK:</b> {invite_link}\n"
        f"👥 <b>GROUP MEMBERS:</b> {member_count}\n"
        f"🤵 <b>ADDED BY:</b> {added_by_name}"
    )

    await _log(context, log_text)


async def handle_forfeit_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dismisses the forfeit confirmation dialog without doing anything."""
    query = update.callback_query
    try:
        await context.bot.delete_message(
            chat_id=query.from_user.id, message_id=query.message.message_id
        )
    except Exception:
        pass
    await query.answer("Cancelled — you stayed in the match.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("tr:join:"):
        await tournament_join_callback(update, context)
    elif data.startswith("ts:"):
        await tournament_setup_callback(update, context)
    elif data.startswith("join:"):
        await handle_join_callback(update, context)
    elif data.startswith("cancel_room:"):
        await handle_cancel_room_callback(update, context)
    elif data.startswith("card:"):
        await handle_card_callback(update, context)
    elif data.startswith("cancel_game:"):
        await handle_cancel_game_callback(update, context)
    elif data.startswith("forfeit_ask:"):
        await handle_forfeit_ask_callback(update, context)
    elif data.startswith("forfeit_confirm:"):
        await handle_forfeit_confirm_callback(update, context)
    elif data.startswith("forfeit_back:"):
        await handle_forfeit_back_callback(update, context)
    elif data.startswith("rematch:"):
        await handle_rematch_callback(update, context)
    elif data.startswith("lb:") or data == "lb_nochat":
        await handle_leaderboard_callback(update, context)
    elif data == "start_help":
        user = query.from_user
        text = f"""❓ <b>VELOCITY BINGO — HOW TO PLAY</b>\n\n🎮 <b>1. CREATE A MATCH</b>\nUse /bingo in a group to create a room, then let another player join using the Join button.\n\n🎴 <b>2. GET YOUR CARD</b>\nBoth players receive a private 5×5 Bingo card containing numbers from 1 to 25.\n\n🔢 <b>3. PLAY YOUR TURN</b>\nPlayers take turns calling numbers. Mark available called numbers on your private card using the buttons.\n\n🏆 <b>4. WIN THE MATCH</b>\nComplete 5 horizontal, vertical, or diagonal Bingo lines before your opponent to win.\n\n💰 <b>5. EARN REWARDS</b>\nA match victory rewards 500 🪙 coins, and your game statistics are updated automatically.\n\n📋 <b>MAIN COMMANDS</b>\n🎮 /bingo — Create a match\n👤 /profile — View your stats\n🏆 /leaderboard — Top players\n🎁 /give — Transfer coins\n❌ /cancel — Cancel/forfeit a game\n🛑 /stopbingo — Admin room control\n\n💡 <b>TIP:</b> Start the bot privately with /start before playing so your private card can be delivered to you."""
        try:
            await query.message.edit_text(text, parse_mode="HTML", reply_markup=await _build_start_keyboard(context), disable_web_page_preview=True)
        except BadRequest:
            pass
        await query.answer()
    else:
        await query.answer()


async def tournament_scheduler(application: Application):
    # Lightweight scheduler: no extra dependency required, works on Render workers.
    while True:
        try:
            from datetime import datetime, timezone
            from tournament import start_tournament
            now = datetime.now(timezone.utc)
            for t in await db.get_open_tournaments():
                start_at = t.get("start_at")
                # MongoDB/JSON-backed records may return start_at as an ISO string.
                # Normalize it to an aware UTC datetime before comparing with `now`.
                if isinstance(start_at, str):
                    try:
                        start_at = start_at.strip()
                        if start_at.endswith("Z"):
                            start_at = start_at[:-1] + "+00:00"
                        start_at = datetime.fromisoformat(start_at)
                    except (TypeError, ValueError):
                        logger.warning("Invalid tournament start_at for %s: %r", t.get("id"), t.get("start_at"))
                        continue
                if isinstance(start_at, datetime) and start_at.tzinfo is None:
                    start_at = start_at.replace(tzinfo=timezone.utc)
                if t.get("status") in ("registration", "scheduled") and start_at and now >= start_at:
                    if await db.tournament_player_count(t["id"]) >= int(t.get("min_players", 2)):
                        await start_tournament(application, t["id"])
                    else:
                        await db.update_tournament(t["id"], status="cancelled", cancel_reason="Minimum player count was not reached before start time")
        except Exception as exc:
            logger.exception("Tournament scheduler error: %s", exc)
        await asyncio.sleep(30)


async def post_init(application: Application):
    await db.init_db()
    application.create_task(tournament_scheduler(application))
    logger.info("Database initialized.")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(MessageHandler(filters.ChatType.GROUPS, register_group_activity), group=-10)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("bingo", cmd_bingo))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stopbingo", cmd_stopbingo))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("give", cmd_give))
    app.add_handler(CommandHandler("tournament_create", cmd_tournament_create))
    app.add_handler(CommandHandler("tournament_manage", cmd_tournament_manage))
    app.add_handler(CommandHandler("tournament_dq", cmd_tournament_dq))
    app.add_handler(CommandHandler("tournament_start", cmd_tournament_start))
    app.add_handler(CommandHandler("tournament_winner", cmd_tournament_winner))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_tournament_input), group=0)
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_webserver()
    main()
