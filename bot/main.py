import os
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
)
from telegram.error import BadRequest, Forbidden

import database as db
from rooms import cmd_bingo, cmd_bet_bingo, handle_join_callback, handle_cancel_room_callback, cmd_stopbingo
from game import handle_card_callback, handle_rematch_callback, _try_unpin, _log
from economy import award_winner, record_loss, settle_bet_result
from leaderboard import build_leaderboard_text, build_leaderboard_keyboard
from utils import display_name_from_db, display_name
from models import LINES_TO_WIN, WIN_COINS, OWNER_ID, LOGGER_GROUP_ID, SUPPORT_CHANNEL

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username, user.first_name)

    name = user.first_name or user.username or "Player"
    await update.message.reply_text(
        f"🎮 <b>Welcome to Velocity Bingo, {name}!</b>\n\n"
        "This is a turn-based Bingo game where YOU call the numbers!\n\n"
        "<b>How to play:</b>\n"
        "1️⃣ Add me to a group chat\n"
        "2️⃣ Use /bingo to create a room\n"
        "3️⃣ A second player joins your room\n"
        "4️⃣ You each get a private 5×5 card (1–25)\n"
        "5️⃣ Take turns calling numbers\n"
        f"6️⃣ First to complete <b>{LINES_TO_WIN} lines</b> wins!\n\n"
        "<b>Commands:</b>\n"
        "/bingo — Create a new match (in a group)\n"
        "/bet_bingo <amount> — Start a coin bet match\n"
        "/cancel — Forfeit your current game\n"
        "/profile — View your stats\n"
        "/leaderboard — See top players\n"
        "/stopbingo — Cancel all rooms (admins only)\n\n"
        "✅ You're registered! Go add me to a group and start playing.",
        parse_mode="HTML",
    )


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
        f"👤 <b>Profile — {name}</b>\n\n"
        f"💰 Coins: <b>{coins:,}</b>\n"
        f"🎮 Games Played: <b>{games}</b>\n"
        f"🏆 Wins: <b>{wins}</b>\n"
        f"😔 Losses: <b>{losses}</b>\n"
        f"📈 Win Rate: <b>{win_rate:.1f}%</b>\n"
        f"🔥 Current Streak: <b>{streak}</b>\n"
        f"⭐ Longest Streak: <b>{longest}</b>",
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
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


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
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except BadRequest:
        pass
    await query.answer()


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    chat_id = room["chat_id"]
    opponent_id = (
        room["player2_id"] if user.id == room["player1_id"] else room["player1_id"]
    )
    opponent = await db.get_user(opponent_id)
    opponent_name = display_name_from_db(opponent) if opponent else "Opponent"

    await db.finish_room(room["id"])
    stake_amount = room.get("stake_amount", 0) or 0
    if stake_amount > 0:
        await settle_bet_result(opponent_id, user.id, stake_amount, chat_id)
    else:
        await asyncio.gather(
            award_winner(opponent_id, chat_id),
            record_loss(user.id, chat_id),
        )

    forfeit_text = (
        f"🏳️ <b>Forfeit — Room #{room['room_number']}</b>\n\n"
        f"😔 <b>{forfeiter_name}</b> forfeited the match.\n"
        f"🥇 <b>{opponent_name}</b> wins by forfeit!\n"
        f"💰 Reward: <b>+{WIN_COINS} Coins</b>"
    )

    live_mid = room.get("live_message_id")
    if live_mid:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=live_mid,
                text=forfeit_text,
                parse_mode="HTML",
            )
        except BadRequest:
            await context.bot.send_message(chat_id=chat_id, text=forfeit_text, parse_mode="HTML")
        await _try_unpin(context, chat_id, live_mid)
    else:
        await context.bot.send_message(chat_id=chat_id, text=forfeit_text, parse_mode="HTML")

    try:
        await context.bot.send_message(
            chat_id=opponent_id,
            text=(
                f"🏆 <b>{forfeiter_name}</b> forfeited!\n"
                f"You win Room <b>#{room['room_number']}</b> by forfeit.\n"
                f"💰 <b>+{WIN_COINS} coins</b> added to your profile."
            ),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        pass

    await update.message.reply_text(
        f"🏳️ You have forfeited <b>Room #{room['room_number']}</b>.\n"
        f"{opponent_name} wins.",
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
            f"✅ Broadcast complete!\n\n"
            f"📨 Sent: <b>{sent}</b>\n"
            f"❌ Failed: <b>{failed}</b>",
            parse_mode="HTML",
        )
    except BadRequest:
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


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("join:"):
        await handle_join_callback(update, context)
    elif data.startswith("cancel_room:"):
        await handle_cancel_room_callback(update, context)
    elif data.startswith("card:"):
        await handle_card_callback(update, context)
    elif data.startswith("rematch:"):
        await handle_rematch_callback(update, context)
    elif data.startswith("lb:") or data == "lb_nochat":
        await handle_leaderboard_callback(update, context)
    else:
        await query.answer()


async def post_init(application: Application):
    await db.init_db()
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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("bingo", cmd_bingo))
    app.add_handler(CommandHandler("bet_bingo", cmd_bet_bingo))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stopbingo", cmd_stopbingo))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
