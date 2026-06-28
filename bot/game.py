import json
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import database as db
from cards import (
    generate_card,
    count_completed_lines,
    build_active_text,
    build_active_keyboard,
    build_locked_text,
    build_locked_keyboard,
    build_popup_card_text,
)
from economy import award_winner, record_loss
from models import WIN_COINS, LINES_TO_WIN
from utils import display_name_from_db, format_called_numbers


def build_live_message(room: dict, p1: dict, p2: dict) -> str:
    called = json.loads(room["called_numbers"])
    called_str = format_called_numbers(called)
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)

    if room["current_turn"] == room["player1_id"]:
        turn_name = p1_name
    else:
        turn_name = p2_name

    phase = room.get("phase", "call")
    last_called = room.get("last_called_number")

    if phase == "call":
        status = f"🎯 {turn_name} is choosing a number..."
    else:
        marker_name = p2_name if room["current_turn"] == room["player1_id"] else p1_name
        status = f"⚡ {marker_name} is marking number <b>{last_called}</b>..."

    return "\n".join([
        f"🎮 <b>Velocity Bingo — Room #{room['room_number']}</b>",
        "",
        f"👤 Player 1: {p1_name}",
        f"👤 Player 2: {p2_name}",
        "",
        f"🎯 Turn: <b>{turn_name}</b>",
        f"📢 Last Called: <b>{last_called if last_called else 'None'}</b>",
        f"📋 Called Numbers: {called_str}",
        "",
        f"🔄 {status}",
    ])


async def _edit_card_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    text: str,
    keyboard,
) -> bool:
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return True
    except BadRequest:
        return False


async def send_card_to_player(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    player_id: int,
    player_name: str,
    opponent_name: str,
    is_my_turn_to_call: bool,
    need_to_mark: bool,
) -> Optional[int]:
    card = await db.get_card(room["id"], player_id)
    if not card:
        return None

    called = json.loads(room["called_numbers"])
    last_called = room.get("last_called_number")
    chat_id = room["chat_id"]
    is_active = is_my_turn_to_call or need_to_mark

    if is_active:
        text = build_active_text(
            room_number=room["room_number"],
            player_name=player_name,
            opponent_name=opponent_name,
            completed_lines=card["completed_lines"],
            called_numbers=called,
            is_my_turn_to_call=is_my_turn_to_call,
            need_to_mark=need_to_mark,
            last_called=last_called,
        )
        keyboard = build_active_keyboard(
            room_id=room["id"],
            numbers=card["numbers"],
            marked=card["marked_numbers"],
            last_called=last_called,
            need_to_mark=need_to_mark,
        )
    else:
        text = build_locked_text(room["room_number"], player_name)
        keyboard = build_locked_keyboard(room["id"], player_id)

    if card.get("card_message_id"):
        success = await _edit_card_message(
            context, chat_id, card["card_message_id"], text, keyboard
        )
        if success:
            return card["card_message_id"]

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await db.update_card_message_id(card["id"], msg.message_id)
    return msg.message_id


async def update_both_cards(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    p1: dict,
    p2: dict,
):
    phase = room.get("phase", "call")
    caller_id = room["current_turn"]
    p1_is_caller = room["player1_id"] == caller_id
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)

    if phase == "call":
        p1_call, p2_call = p1_is_caller, not p1_is_caller
        p1_mark, p2_mark = False, False
    else:
        p1_call, p2_call = False, False
        p1_mark, p2_mark = not p1_is_caller, p1_is_caller

    await asyncio.gather(
        send_card_to_player(context, room, room["player1_id"], p1_name, p2_name, p1_call, p1_mark),
        send_card_to_player(context, room, room["player2_id"], p2_name, p1_name, p2_call, p2_mark),
    )


async def update_live_message(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    p1: dict,
    p2: dict,
):
    if not room.get("live_message_id"):
        return
    text = build_live_message(room, p1, p2)
    try:
        await context.bot.edit_message_text(
            chat_id=room["chat_id"],
            message_id=room["live_message_id"],
            text=text,
            parse_mode="HTML",
        )
    except BadRequest:
        pass


async def handle_view_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    room_id = int(parts[1])
    card_owner_id = int(parts[2])
    viewer_id = query.from_user.id

    if viewer_id != card_owner_id:
        await query.answer("🚫 This is not your card!", show_alert=True)
        return

    room = await db.get_room(room_id)
    if not room or room["status"] not in ("playing",):
        await query.answer("This game is no longer active.", show_alert=True)
        return

    card = await db.get_card(room_id, viewer_id)
    if not card:
        await query.answer("Card not found.", show_alert=True)
        return

    popup_text = build_popup_card_text(
        room_number=room["room_number"],
        numbers=card["numbers"],
        marked=card["marked_numbers"],
        completed_lines=card["completed_lines"],
    )
    await query.answer(popup_text, show_alert=True, cache_time=0)


async def handle_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return

    room_id = int(parts[1])
    number = int(parts[2])
    player_id = query.from_user.id

    room = await db.get_room(room_id)
    if not room or room["status"] != "playing":
        await query.answer("This game is no longer active.", show_alert=True)
        return

    if player_id not in (room["player1_id"], room["player2_id"]):
        await query.answer("🚫 You are not in this game!", show_alert=True)
        return

    called = json.loads(room["called_numbers"])
    phase = room.get("phase", "call")
    caller_id = room["current_turn"]
    last_called = room.get("last_called_number")

    p1 = await db.get_user(room["player1_id"])
    p2 = await db.get_user(room["player2_id"])

    if phase == "call":
        if player_id != caller_id:
            other = p1 if room["player2_id"] == player_id else p2
            await query.answer(
                f"⏳ Not your turn! Wait for {display_name_from_db(other)}.",
                show_alert=True,
            )
            return

        if number in called:
            await query.answer("🚫 That number was already called!", show_alert=True)
            return

        await query.answer(f"📢 You called {number}!")

        called.append(number)
        await db.update_room(room_id, called_numbers=json.dumps(called),
                             last_called_number=number, phase="mark")

        card = await db.get_card(room_id, player_id)
        new_lines = count_completed_lines(card["numbers"], card["marked_numbers"] + [number])
        await db.mark_number(card["id"], number, new_lines)

        if new_lines >= LINES_TO_WIN:
            await handle_bingo_win(context, room, player_id, p1, p2, called)
            return

        caller_name = display_name_from_db(p1 if room["player1_id"] == player_id else p2)
        await context.bot.send_message(
            chat_id=room["chat_id"],
            text=f"🎲 <b>Room #{room['room_number']}</b> — {caller_name} called <b>{number}</b>!",
            parse_mode="HTML",
        )

        room = await db.get_room(room_id)
        await asyncio.gather(
            update_live_message(context, room, p1, p2),
            update_both_cards(context, room, p1, p2),
        )

    elif phase == "mark":
        marker_id = room["player2_id"] if caller_id == room["player1_id"] else room["player1_id"]

        if player_id != marker_id:
            await query.answer(
                f"⏳ Wait — the other player needs to mark {last_called}!",
                show_alert=True,
            )
            return

        if number != last_called:
            await query.answer(
                f"🚫 You must mark the called number: {last_called}",
                show_alert=True,
            )
            return

        await query.answer(f"✅ Marked {number}!")

        card = await db.get_card(room_id, player_id)
        new_lines = count_completed_lines(card["numbers"], card["marked_numbers"] + [number])
        await db.mark_number(card["id"], number, new_lines)

        if new_lines >= LINES_TO_WIN:
            room = await db.get_room(room_id)
            await handle_bingo_win(context, room, player_id, p1, p2, called)
            return

        await db.update_room(room_id, current_turn=player_id, phase="call")

        room = await db.get_room(room_id)
        await asyncio.gather(
            update_live_message(context, room, p1, p2),
            update_both_cards(context, room, p1, p2),
        )


async def handle_bingo_win(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    winner_id: int,
    p1: dict,
    p2: dict,
    called: list,
):
    loser_id = room["player2_id"] if winner_id == room["player1_id"] else room["player1_id"]
    await db.finish_room(room["id"])
    await asyncio.gather(award_winner(winner_id), record_loss(loser_id))

    winner = p1 if winner_id == room["player1_id"] else p2
    winner_name = display_name_from_db(winner)

    win_text = (
        f"🏆 <b>BINGO!</b>\n\n"
        f"🥇 Winner: <b>{winner_name}</b>\n"
        f"🏠 Room: <b>#{room['room_number']}</b>\n"
        f"💰 Reward: <b>+{WIN_COINS} Coins</b>\n\n"
        f"📋 Numbers called: {format_called_numbers(called)}"
    )

    if room.get("live_message_id"):
        try:
            await context.bot.edit_message_text(
                chat_id=room["chat_id"],
                message_id=room["live_message_id"],
                text=win_text,
                parse_mode="HTML",
            )
        except BadRequest:
            await context.bot.send_message(
                chat_id=room["chat_id"], text=win_text, parse_mode="HTML"
            )
    else:
        await context.bot.send_message(
            chat_id=room["chat_id"], text=win_text, parse_mode="HTML"
        )

    for card_owner_id in (room["player1_id"], room["player2_id"]):
        card = await db.get_card(room["id"], card_owner_id)
        if card and card.get("card_message_id"):
            owner = p1 if card_owner_id == room["player1_id"] else p2
            owner_name = display_name_from_db(owner)
            final_text = (
                f"🏁 <b>Game Over — Room #{room['room_number']}</b>\n\n"
                f"{'🏆 You won!' if card_owner_id == winner_id else '😔 You lost.'}\n"
                f"Winner: <b>{winner_name}</b>"
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=room["chat_id"],
                    message_id=card["card_message_id"],
                    text=final_text,
                    parse_mode="HTML",
                )
            except BadRequest:
                pass


async def start_game_countdown(
    context: ContextTypes.DEFAULT_TYPE,
    room_id: int,
    chat_id: int,
    p1: dict,
    p2: dict,
    room_message_id: int,
):
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)

    for count in range(5, 0, -1):
        text = (
            f"🎉 <b>Opponent Found!</b>\n\n"
            f"👤 Player 1: {p1_name}\n"
            f"👤 Player 2: {p2_name}\n\n"
            f"⏳ Game starts in <b>{count}...</b>"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=room_message_id,
                text=text,
                parse_mode="HTML",
            )
        except BadRequest:
            pass
        await asyncio.sleep(1)

    card1 = generate_card()
    card2 = generate_card()
    await db.create_card(room_id, p1["telegram_id"], card1)
    await db.create_card(room_id, p2["telegram_id"], card2)

    await db.update_room(
        room_id,
        current_turn=p1["telegram_id"],
        phase="call",
        last_called_number=None,
        called_numbers="[]",
    )

    room = await db.get_room(room_id)

    live_text = build_live_message(room, p1, p2)
    try:
        live_msg = await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=room_message_id,
            text=live_text,
            parse_mode="HTML",
        )
        live_message_id = live_msg.message_id
    except BadRequest:
        live_msg = await context.bot.send_message(
            chat_id=chat_id, text=live_text, parse_mode="HTML"
        )
        live_message_id = live_msg.message_id

    await db.update_room(room_id, live_message_id=live_message_id)
    room = await db.get_room(room_id)

    for pid, pname in [(p1["telegram_id"], p1_name), (p2["telegram_id"], p2_name)]:
        card = await db.get_card(room_id, pid)
        is_caller = pid == p1["telegram_id"]
        text = build_active_text(
            room_number=room["room_number"],
            player_name=pname,
            opponent_name=p2_name if is_caller else p1_name,
            completed_lines=0,
            called_numbers=[],
            is_my_turn_to_call=is_caller,
            need_to_mark=False,
            last_called=None,
        )
        keyboard = build_active_keyboard(
            room_id=room_id,
            numbers=card["numbers"],
            marked=card["marked_numbers"],
            last_called=None,
            need_to_mark=False,
        )
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await db.update_card_message_id(card["id"], msg.message_id)

    await asyncio.sleep(0.5)
    card1_db = await db.get_card(room_id, p2["telegram_id"])
    if card1_db and card1_db.get("card_message_id"):
        locked_text = build_locked_text(room["room_number"], p2_name)
        locked_kb = build_locked_keyboard(room_id, p2["telegram_id"])
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=card1_db["card_message_id"],
                text=locked_text,
                reply_markup=locked_kb,
                parse_mode="HTML",
            )
        except BadRequest:
            pass
