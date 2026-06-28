import os
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import BadRequest, Forbidden

import database as db
from rooms import cmd_bingo, handle_join_callback, handle_cancel_room_callback, cmd_stopbingo
from game import handle_card_callback, handle_rematch_callback
from economy import award_winner, record_loss
from leaderboard import build_leaderboard_text
from utils import display_name_from_db
from models import LINES_TO_WIN, WIN_COINS

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
    text = await build_leaderboard_text()
    await update.message.reply_text(text, parse_mode="HTML")


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

    opponent_id = (
        room["player2_id"] if user.id == room["player1_id"] else room["player1_id"]
    )
    opponent = await db.get_user(opponent_id)
    opponent_name = display_name_from_db(opponent) if opponent else "Opponent"

    await db.finish_room(room["id"])
    await asyncio.gather(
        award_winner(opponent_id),
        record_loss(user.id),
    )

    forfeit_text = (
        f"🏳️ <b>Forfeit — Room #{room['room_number']}</b>\n\n"
        f"😔 <b>{forfeiter_name}</b> forfeited the match.\n"
        f"🥇 <b>{opponent_name}</b> wins by forfeit!\n"
        f"💰 Reward: <b>+{WIN_COINS} Coins</b>"
    )

    if room.get("live_message_id"):
        try:
            await context.bot.edit_message_text(
                chat_id=room["chat_id"],
                message_id=room["live_message_id"],
                text=forfeit_text,
                parse_mode="HTML",
            )
        except BadRequest:
            await context.bot.send_message(
                chat_id=room["chat_id"], text=forfeit_text, parse_mode="HTML"
            )
    else:
        await context.bot.send_message(
            chat_id=room["chat_id"], text=forfeit_text, parse_mode="HTML"
        )

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
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stopbingo", cmd_stopbingo))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
