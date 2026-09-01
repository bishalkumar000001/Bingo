import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
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
from tournament import (
    cmd_tournament,
    cmd_tournament_add,
    cmd_tournament_start,
    cmd_tournament_status,
    cmd_announce_tournament,
    cmd_playerlist,
    cmd_cancel_tournament,
    handle_tournament_join,
    handle_tournament_leave,
    handle_tournament_status_callback,
    handle_tournament_forfeit,
)
from utils import display_name_from_db, display_name
from models import LINES_TO_WIN, WIN_COINS, FORFEIT_COST, CANCEL_FREE_THRESHOLD, OWNER_ID, LOGGER_GROUP_ID, SUPPORT_CHANNEL

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _send_help_message(update: Update, context: ContextTypes.DEFAULT_TYPE, *, via_callback=False):
    user = update.effective_user
    name = user.first_name or user.username or "Player"
    text = f"""🎮 𝗪𝗲𝗹𝗰𝗼𝗺𝗲, ─ {name}

🎯 𝗦𝘁𝗮𝗿𝘁 𝗮 𝗚𝗮𝗺𝗲

🎮 Create or join a 1v1 match with another player.
🤝 Once both players join, the game begins.
🔢 Each player gets a 5×5 Bingo card with numbers 1–25.

📩 Start the bot in private using /start to receive your card and game updates.

🔄 𝗛𝗼𝘄 𝘁𝗵𝗲 𝗚𝗮𝗺𝗲 𝗪𝗼𝗿𝗸𝘀
👆 Players take turns choosing numbers.
✅ The selected number is marked on both Bingo cards.
🧠 Complete your lines before your opponent!

🏆 𝗛𝗼𝘄 𝘁𝗼 𝗪𝗶𝗻
Complete 5 full lines to make BINGO:
➖ Rows — Left to right
⬇️ Columns — Top to bottom
✖️ Diagonals — Across the card

🎉 The first player to complete 5 lines wins the match! 👑🏆

🥇 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱
Compete with other players and fight for the #1 spot! 👑

❌ 𝗖𝗮𝗻𝗰𝗲𝗹𝗹𝗶𝗻𝗴 & 𝗙𝗮𝗶𝗿 𝗣𝗹𝗮𝘆
Use /cancel if you cannot continue the current match. 🤝
⚠️ Play fairly and don't keep your opponent waiting!

✨ 𝗤𝘂𝗶𝗰𝗸 𝗦𝘁𝗮𝗿𝘁
1️⃣ Start the Bot → 2️⃣ Join a Match → 3️⃣ Play → 4️⃣ Complete BINGO → 5️⃣ WIN! 🏆"""
    buttons = [[InlineKeyboardButton("📢 Support Channel", url=SUPPORT_CHANNEL)]] if SUPPORT_CHANNEL.startswith(("http://", "https://")) else []
    markup = InlineKeyboardMarkup(buttons)
    if via_callback:
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username, user.first_name)

    name = user.first_name or user.username or "Player"
    text = f"""🎮 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 ─͢ {name} 🎉
🎯 𝗛𝗼𝘄 𝘁𝗼 𝗣𝗹𝗮𝘆?
● Start a 1v1 game and challenge another player.
● Both players get a 5x5 Bingo card with numbers 1-25.
● Take turns choosing numbers.
● The chosen number is marked on both cards.
● Complete 5 lines — Rows, Columns or Diagonals — to complete BINGO. The first player to complete it wins 🎊

💰 𝗣𝗹𝗮𝘆 & 𝗘𝗮𝗿𝗻
● 𝗪𝗶𝗻 𝗺𝗮𝘁𝗰𝗵𝗲𝘀 𝗮𝗻𝗱 𝗲𝗮𝗿𝗻 𝗕𝗶𝗻𝗴𝗼 𝗖𝗼𝗶𝗻𝘀
● 𝗖𝗵𝗲𝗰𝗸 𝘆𝗼𝘂𝗿 𝗦𝘁𝗮𝘁𝘀 & 𝗪𝗶𝗻𝘀
● 𝗖𝗹𝗶𝗺𝗯 𝘁𝗵𝗲 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱
● 𝗝𝗼𝗶𝗻 𝗧𝗼𝘂𝗿𝗻𝗮𝗺𝗲𝗻𝘁𝘀 & 𝗰𝗼𝗺𝗽𝗲𝘁𝗲 𝗳𝗼𝗿 𝗿𝗲𝘄𝗮𝗿𝗱𝘀!

✨ 𝗡𝗼 𝗰𝗼𝗺𝗽𝗹𝗶𝗰𝗮𝘁𝗲𝗱 𝗿𝘂𝗹𝗲𝘀 — 𝗷𝘂𝘀𝘁 𝗽𝗹𝗮𝘆, 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝘆𝗼𝘂𝗿 𝗕𝗜𝗡𝗚𝗢 & 𝗵𝗮𝘃𝗲 𝗳𝘂𝗻! ❤️

👇 Start playing with your friends. 🎮
/bingo = to start the match.
/leaderboard = rankings of the top ten users
/profile = for your stats
/tournament_status = view the current tournament

👑 𝗣𝗹𝗮𝘆 • 𝗪𝗶𝗻 • 𝗕𝗲𝗰𝗼𝗺𝗲 𝘁𝗵𝗲 𝗕𝗶𝗻𝗴𝗼 𝗖𝗵𝗮𝗺𝗽𝗶𝗼𝗻! 🏆"""
    bot_username = context.bot.username
    add_me_url = f"https://t.me/{bot_username}?startgroup=true" if bot_username else None
    first_row = []
    if SUPPORT_CHANNEL.startswith(("http://", "https://")):
        first_row.append(InlineKeyboardButton("📢 Support Channel", url=SUPPORT_CHANNEL))
    if add_me_url:
        first_row.append(InlineKeyboardButton("➕ Add Me", url=add_me_url))
    keyboard_rows = []
    if first_row:
        keyboard_rows.append(first_row)
    keyboard_rows.append([InlineKeyboardButton("ℹ️ Detail Help", callback_data="detail_help")])
    keyboard = InlineKeyboardMarkup(keyboard_rows)
    await update.message.reply_text(text, reply_markup=keyboard)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_help_message(update, context)


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

    # Tournament matches cannot be silently cancelled: doing so would leave
    # the knockout bracket waiting forever. A /cancel is recorded as a loss.
    if room.get("tournament_id"):
        await handle_tournament_forfeit(context, room, opponent_id)
        await update.message.reply_text(
            f"🏳️ You forfeited tournament match #{room['room_number']}.\n"
            f"✅ {opponent_name} advances to the next round."
        )
        return

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

    if not OWNER_ID or user.id != OWNER_ID:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    source = update.message.reply_to_message
    if not source and not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "• Reply to a message with /broadcast to send it to all players and groups\n"
            "• /broadcast <text> to send a plain message to all players and groups"
        )
        return

    user_ids = await db.get_all_user_ids()
    group_ids = await db.get_all_group_chat_ids()

    status_msg = await update.message.reply_text(
        f"📡 Broadcasting to <b>{len(user_ids)}</b> players and <b>{len(group_ids)}</b> Telegram groups...",
        parse_mode="HTML",
    )

    sent_users = failed_users = sent_groups = failed_groups = 0

    for uid in user_ids:
        try:
            if source:
                await source.copy(chat_id=uid)
            else:
                await context.bot.send_message(
                    chat_id=uid, text=" ".join(context.args), parse_mode="HTML"
                )
            sent_users += 1
        except (Forbidden, BadRequest):
            failed_users += 1
        except Exception:
            failed_users += 1
        await asyncio.sleep(0.05)

    for gid in group_ids:
        try:
            if source:
                await source.copy(chat_id=gid)
            else:
                await context.bot.send_message(
                    chat_id=gid, text=" ".join(context.args), parse_mode="HTML"
                )
            sent_groups += 1
        except (Forbidden, BadRequest):
            failed_groups += 1
        except Exception:
            failed_groups += 1
        await asyncio.sleep(0.05)

    try:
        await status_msg.edit_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Broadcast Complete!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Player DMs</b>\n📨 Sent: <b>{sent_users}</b>\n❌ Failed: <b>{failed_users}</b>\n\n"
            f"👥 <b>Telegram Groups</b>\n📨 Sent: <b>{sent_groups}</b>\n❌ Failed: <b>{failed_groups}</b>\n\n"
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
    
    if user.id != OWNER_ID and sender["coins"] < amount:
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
    if user.id == OWNER_ID:
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


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if new_status in ("member", "administrator"):
        await db.register_group_chat(chat.id, chat.title or "", chat.username or "")

    if new_status not in ("member", "administrator"):
        return
    if old_status in ("member", "administrator"):
        return

    if not LOGGER_GROUP_ID:
        return

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
    if not query or not query.data:
        return
    data = query.data

    if data == "tournament_join":
        await handle_tournament_join(update, context)
        return
    if data.startswith("tournament_join:"):
        await handle_tournament_join(update, context)
        return
    if data.startswith("tournament_leave:"):
        await handle_tournament_leave(update, context)
        return
    if data.startswith("tournament_status:"):
        await handle_tournament_status_callback(update, context)
        return
    if data == "detail_help":
        await query.answer()
        await _send_help_message(update, context, via_callback=True)
        return
    if data == "support_channel":
        if SUPPORT_CHANNEL and SUPPORT_CHANNEL.startswith(("http://", "https://")):
            await query.answer()
            await query.message.reply_text("📢 Join our support channel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 Open Support Channel", url=SUPPORT_CHANNEL)]]))
        else:
            await query.answer("Support channel is not configured yet.", show_alert=True)
        return
    if data == "add_me":
        await query.answer("Add this bot to your group, then use /bingo to start a match.", show_alert=True)
        return

    if data.startswith("join:"):
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
    else:
        await query.answer()


async def post_init(application: Application):
    for attempt in range(1, 6):
        try:
            await db.init_db()
            logger.info("Database initialized.")
            return
        except Exception:
            logger.exception("Database initialization failed (attempt %s/5)", attempt)
            if attempt == 5:
                raise
            await asyncio.sleep(min(30, 2 ** attempt))


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if error:
        logger.error(
            "Unhandled Telegram update error",
            exc_info=(type(error), error, error.__traceback__),
        )
    query = getattr(update, "callback_query", None)
    if query:
        try:
            await query.answer(
                "Something went wrong temporarily. Please try again.",
                show_alert=True,
            )
        except Exception:
            pass


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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("bingo", cmd_bingo))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stopbingo", cmd_stopbingo))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("tournament", cmd_tournament))
    app.add_handler(CommandHandler("tournament_add", cmd_tournament_add))
    app.add_handler(CommandHandler("tournament_start", cmd_tournament_start))
    app.add_handler(CommandHandler("tournament_status", cmd_tournament_status))
    app.add_handler(CommandHandler("announce", cmd_announce_tournament))
    app.add_handler(CommandHandler("playerlist", cmd_playerlist))
    app.add_handler(CommandHandler("cancel_tournament", cmd_cancel_tournament))
    app.add_handler(CommandHandler("give", cmd_give))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(handle_error)

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_webserver()
    main()
