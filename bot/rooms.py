import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import database as db
from models import MAX_ROOMS_PER_CHAT
from utils import display_name, display_name_from_db
from game import start_game_countdown, _try_unpin


def build_waiting_keyboard(room_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Join Match", callback_data=f"join:{room_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_room:{room_id}"),
            ]
        ]
    )


async def cmd_bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text(
            "⚠️ Use /bingo in a group chat to start a match!"
        )
        return

    player = await db.get_user(user.id)
    if not player:
        await update.message.reply_text(
            "❌ You need to register first! Send /start to me in a private chat."
        )
        return

    if await db.is_player_in_active_room(user.id):
        await update.message.reply_text(
            "❌ You are already in an active match! Finish it first."
        )
        return

    active_rooms = await db.get_active_rooms_in_chat(chat.id)
    if len(active_rooms) >= MAX_ROOMS_PER_CHAT:
        await update.message.reply_text(
            f"❌ This group already has {MAX_ROOMS_PER_CHAT} active rooms running.\n"
            "Wait for a match to finish!"
        )
        return

    room_number = await db.get_next_room_number(chat.id)
    if room_number == -1:
        await update.message.reply_text("❌ No room slots available!")
        return

    player_name = display_name(user)

    placeholder = await update.message.reply_text("🎮 Creating room...")

    room_id = await db.create_room(
        chat_id=chat.id,
        room_number=room_number,
        player1_id=user.id,
        room_message_id=placeholder.message_id,
    )

    text = (
        f"🎮 <b>Velocity Bingo — Room #{room_number}</b>\n\n"
        f"👤 Player 1: {player_name}\n\n"
        f"⏳ Waiting for an opponent...\n"
        f"👥 Players: 1 / 2"
    )
    keyboard = build_waiting_keyboard(room_id)
    await placeholder.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def cmd_bet_bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("⚠️ Use /bet_bingo in a group chat to start a bet match!")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /bet_bingo <amount>\nExample: /bet_bingo 100"
        )
        return

    try:
        stake_amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Bet amount must be a whole number of coins.")
        return

    if stake_amount <= 0:
        await update.message.reply_text("❌ Bet amount must be greater than 0.")
        return

    player = await db.get_user(user.id)
    if not player:
        await update.message.reply_text(
            "❌ You need to register first! Send /start to me in a private chat."
        )
        return

    if player["coins"] < stake_amount:
        await update.message.reply_text(
            f"❌ You need at least {stake_amount} coins to create this bet room."
        )
        return

    if await db.is_player_in_active_room(user.id):
        await update.message.reply_text(
            "❌ You are already in an active match! Finish it first."
        )
        return

    active_rooms = await db.get_active_rooms_in_chat(chat.id)
    if len(active_rooms) >= MAX_ROOMS_PER_CHAT:
        await update.message.reply_text(
            f"❌ This group already has {MAX_ROOMS_PER_CHAT} active rooms running.\n"
            "Wait for a match to finish!"
        )
        return

    room_number = await db.get_next_room_number(chat.id)
    if room_number == -1:
        await update.message.reply_text("❌ No room slots available!")
        return

    player_name = display_name(user)
    placeholder = await update.message.reply_text("🎮 Creating bet room...")

    room_id = await db.create_room(
        chat_id=chat.id,
        room_number=room_number,
        player1_id=user.id,
        room_message_id=placeholder.message_id,
        stake_amount=stake_amount,
    )

    text = (
        f"🎮 <b>Velocity Bingo — Room #{room_number}</b>\n\n"
        f"👤 Player 1: {player_name}\n"
        f"💸 Bet: <b>{stake_amount}</b> coins\n\n"
        f"⏳ Waiting for an opponent...\n"
        f"👥 Players: 1 / 2"
    )
    keyboard = build_waiting_keyboard(room_id)
    await placeholder.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def handle_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    data = query.data
    room_id = data.split(":")[1]

    room = await db.get_room(room_id)
    if not room:
        await query.answer("Room not found!", show_alert=True)
        return

    if room["status"] != "waiting":
        await query.answer("This room is no longer open.", show_alert=True)
        return

    if room["player1_id"] == user.id:
        await query.answer("You created this room — wait for an opponent!", show_alert=True)
        return

    player = await db.get_user(user.id)
    if not player:
        await query.answer(
            "You need to register first! Send /start to the bot in a private chat.",
            show_alert=True,
        )
        return

    if await db.is_player_in_active_room(user.id):
        await query.answer(
            "You are already in an active match!", show_alert=True
        )
        return

    stake_amount = room.get("stake_amount", 0) or 0
    if stake_amount > 0 and player["coins"] < stake_amount:
        await query.answer(
            f"❌ You need at least {stake_amount} coins to join this bet match.",
            show_alert=True,
        )
        return

    await query.answer("🎮 Joining match...")
    await db.join_room(room_id, user.id)
    room = await db.get_room(room_id)

    p1 = await db.get_user(room["player1_id"])
    p2 = await db.get_user(room["player2_id"])

    asyncio.create_task(
        start_game_countdown(
            context,
            room_id=room_id,
            chat_id=room["chat_id"],
            p1=p1,
            p2=p2,
            room_message_id=room["room_message_id"],
        )
    )


async def handle_cancel_room_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    data = query.data
    room_id = data.split(":")[1]

    room = await db.get_room(room_id)
    if not room:
        await query.answer("Room not found!", show_alert=True)
        return

    if room["status"] != "waiting":
        await query.answer("The game has already started.", show_alert=True)
        return

    if room["player1_id"] != user.id:
        chat_member = await context.bot.get_chat_member(room["chat_id"], user.id)
        if chat_member.status not in ("administrator", "creator"):
            await query.answer("Only the room creator or admins can cancel!", show_alert=True)
            return

    await db.cancel_room(room_id)
    try:
        await query.edit_message_text(
            f"❌ <b>Room #{room['room_number']}</b> has been cancelled.",
            parse_mode="HTML",
        )
    except BadRequest:
        pass
    await query.answer("Room cancelled.")


async def cmd_stopbingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("Use /stopbingo in a group chat.")
        return

    chat_member = await context.bot.get_chat_member(chat.id, user.id)
    if chat_member.status not in ("administrator", "creator"):
        await update.message.reply_text("❌ Only group admins can use /stopbingo.")
        return

    active_rooms = await db.get_active_rooms_in_chat(chat.id)
    if not active_rooms:
        await update.message.reply_text("No active rooms in this group.")
        return

    for room in active_rooms:
        await db.cancel_room(room["id"])
        live_mid = room.get("live_message_id")
        if live_mid:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=live_mid,
                    text=f"🛑 Room #{room['room_number']} was stopped by an admin.",
                    parse_mode="HTML",
                )
            except BadRequest:
                pass
            await _try_unpin(context, chat.id, live_mid)

    await update.message.reply_text(
        f"🛑 Stopped {len(active_rooms)} active room(s) in this group."
    )
