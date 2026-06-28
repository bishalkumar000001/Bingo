import json
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

import database as db
from cards import (
    generate_card,
    count_completed_lines,
    build_card_keyboard,
    build_card_text,
    get_bingo_status,
)
from economy import award_winner, record_loss
from models import WIN_COINS, LINES_TO_WIN
from utils import display_name, display_name_from_db, format_called_numbers, mention


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
        if room["current_turn"] == room["player1_id"]:
            marker_name = p2_name
        else:
            marker_name = p1_name
        status = f"⚡ {marker_name} is marking number <b>{last_called}</b>..."

    lines = [
        f"🎮 <b>Velocity Bingo — Room #{room['room_number']}</b>",
        "",
        f"👤 Player 1: {p1_name}",
        f"👤 Player 2: {p2_name}",
        "",
        f"🎯 Turn: <b>{turn_name}</b>",
        f"📢 Last Called: <b>{last_called if last_called else 'None'}</b>",
        f"📋 Called Numbers: {called_str}",
        "",
        f"🔄 Status: {status}",
    ]
    return "\n".join(lines)


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
    phase = room.get("phase", "call")

    text = build_card_text(
        room_number=room["room_number"],
        player_name=player_name,
        opponent_name=opponent_name,
        numbers=card["numbers"],
        marked=card["marked_numbers"],
        completed_lines=card["completed_lines"],
        called_numbers=called,
        is_my_turn_to_call=is_my_turn_to_call,
        need_to_mark=need_to_mark,
        last_called=last_called,
    )
    keyboard = build_card_keyboard(
        room_id=room["id"],
        numbers=card["numbers"],
        marked=card["marked_numbers"],
        called_numbers=called,
        last_called=last_called,
        is_my_turn_to_call=is_my_turn_to_call,
        need_to_mark=need_to_mark,
    )

    try:
        if card.get("card_message_id"):
            try:
                await context.bot.edit_message_text(
                    chat_id=player_id,
                    message_id=card["card_message_id"],
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return card["card_message_id"]
            except BadRequest:
                pass

        msg = await context.bot.send_message(
            chat_id=player_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await db.update_card_message_id(card["id"], msg.message_id)
        return msg.message_id
    except (Forbidden, BadRequest):
        return None


async def update_both_cards(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    p1: dict,
    p2: dict,
):
    phase = room.get("phase", "call")
    caller_id = room["current_turn"]

    p1_is_caller = room["player1_id"] == caller_id
    p2_is_caller = room["player2_id"] == caller_id

    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)

    if phase == "call":
        p1_my_turn = p1_is_caller
        p2_my_turn = p2_is_caller
        p1_need_mark = False
        p2_need_mark = False
    else:
        p1_my_turn = False
        p2_my_turn = False
        p1_need_mark = not p1_is_caller
        p2_need_mark = not p2_is_caller

    await asyncio.gather(
        send_card_to_player(
            context, room, room["player1_id"], p1_name, p2_name,
            p1_my_turn, p1_need_mark,
        ),
        send_card_to_player(
            context, room, room["player2_id"], p2_name, p1_name,
            p2_my_turn, p2_need_mark,
        ),
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


async def handle_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")
    if len(parts) != 3:
        return

    _, room_id_str, num_str = parts
    room_id = int(room_id_str)
    number = int(num_str)
    player_id = query.from_user.id

    room = await db.get_room(room_id)
    if not room or room["status"] != "playing":
        await query.answer("This game is no longer active.", show_alert=True)
        return

    if player_id not in (room["player1_id"], room["player2_id"]):
        await query.answer("You are not in this game!", show_alert=True)
        return

    called = json.loads(room["called_numbers"])
    phase = room.get("phase", "call")
    caller_id = room["current_turn"]
    last_called = room.get("last_called_number")

    p1 = await db.get_user(room["player1_id"])
    p2 = await db.get_user(room["player2_id"])

    if phase == "call":
        if player_id != caller_id:
            other_name = display_name_from_db(p1 if room["player2_id"] == player_id else p2)
            await query.answer(f"⏳ It's not your turn! Wait for {other_name}.", show_alert=True)
            return

        if number in called:
            await query.answer("🚫 That number has already been called!", show_alert=True)
            return

        called.append(number)
        await db.update_room(
            room_id,
            called_numbers=json.dumps(called),
            last_called_number=number,
            phase="mark",
        )

        card = await db.get_card(room_id, player_id)
        new_lines = count_completed_lines(card["numbers"], card["marked_numbers"] + [number])
        await db.mark_number(card["id"], number, new_lines)

        if new_lines >= LINES_TO_WIN:
            await handle_bingo_win(context, room, player_id, p1, p2, called)
            return

        caller_name = display_name_from_db(p1 if room["player1_id"] == player_id else p2)
        chat_id = room["chat_id"]
        room_number = room["room_number"]

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎲 <b>Room #{room_number}</b> — {caller_name} called <b>{number}</b>!",
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
                f"⏳ Wait — the other player is marking number {last_called}!", show_alert=True
            )
            return

        if number != last_called:
            await query.answer(
                f"🚫 Please mark the called number: {last_called}", show_alert=True
            )
            return

        card = await db.get_card(room_id, player_id)
        new_lines = count_completed_lines(card["numbers"], card["marked_numbers"] + [number])
        await db.mark_number(card["id"], number, new_lines)

        if new_lines >= LINES_TO_WIN:
            room = await db.get_room(room_id)
            await handle_bingo_win(context, room, player_id, p1, p2, called)
            return

        new_caller = player_id
        await db.update_room(
            room_id,
            current_turn=new_caller,
            phase="call",
        )

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

    await asyncio.gather(
        award_winner(winner_id),
        record_loss(loser_id),
    )

    winner = p1 if winner_id == room["player1_id"] else p2
    winner_name = display_name_from_db(winner)

    win_text = (
        f"🏆 <b>BINGO!</b>\n\n"
        f"Winner: <b>{winner_name}</b>\n"
        f"Room: <b>#{room['room_number']}</b>\n"
        f"Reward: <b>+{WIN_COINS} Coins 💰</b>\n\n"
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

    try:
        await context.bot.send_message(
            chat_id=winner_id,
            text=f"🏆 You won! <b>+{WIN_COINS} coins</b> added to your account!",
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        await context.bot.send_message(
            chat_id=loser_id,
            text=f"😔 You lost this round. Better luck next time!\n{winner_name} won Room #{room['room_number']}.",
            parse_mode="HTML",
        )
    except Exception:
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

    room = await db.get_room(room_id)

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

    dm_failed = []
    for pid, pname, oname in [
        (p1["telegram_id"], p1_name, p2_name),
        (p2["telegram_id"], p2_name, p1_name),
    ]:
        try:
            is_caller = pid == p1["telegram_id"]
            card = await db.get_card(room_id, pid)
            text = build_card_text(
                room_number=room["room_number"],
                player_name=pname,
                opponent_name=oname,
                numbers=card["numbers"],
                marked=card["marked_numbers"],
                completed_lines=0,
                called_numbers=[],
                is_my_turn_to_call=is_caller,
                need_to_mark=False,
                last_called=None,
            )
            keyboard = build_card_keyboard(
                room_id=room_id,
                numbers=card["numbers"],
                marked=card["marked_numbers"],
                called_numbers=[],
                last_called=None,
                is_my_turn_to_call=is_caller,
                need_to_mark=False,
            )
            msg = await context.bot.send_message(
                chat_id=pid,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            await db.update_card_message_id(card["id"], msg.message_id)
        except (Forbidden, BadRequest):
            dm_failed.append(pname)

    if dm_failed:
        names = ", ".join(dm_failed)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ Could not send private cards to: <b>{names}</b>\n"
                f"Please start a DM with the bot first by clicking: @VelocityBingoBot"
            ),
            parse_mode="HTML",
        )
