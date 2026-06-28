import json
import asyncio
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden

import database as db
from cards import (
    generate_card,
    count_completed_lines,
    build_dm_card_text,
    build_dm_card_keyboard,
    build_group_turn_text,
    build_group_turn_keyboard,
    build_group_waiting_text,
)
from economy import award_winner, record_loss
from models import WIN_COINS, LINES_TO_WIN
from utils import display_name_from_db, format_called_numbers


def build_live_message(room: dict, p1: dict, p2: dict) -> str:
    called = json.loads(room["called_numbers"])
    called_str = format_called_numbers(called)
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)
    turn_name = p1_name if room["current_turn"] == room["player1_id"] else p2_name
    phase = room.get("phase", "call")
    last_called = room.get("last_called_number")

    if phase == "call":
        status = f"🎯 <b>{turn_name}</b> is choosing a number..."
    else:
        marker_name = p2_name if room["current_turn"] == room["player1_id"] else p1_name
        status = f"⚡ <b>{marker_name}</b> is marking number <b>{last_called}</b>..."

    return "\n".join([
        f"🎮 <b>Velocity Bingo — Room #{room['room_number']}</b>",
        "",
        f"👤 Player 1: {p1_name}",
        f"👤 Player 2: {p2_name}",
        "",
        f"🎯 Turn: <b>{turn_name}</b>",
        f"📢 Last Called: <b>{last_called if last_called else 'None'}</b>",
        f"📋 Called: {called_str}",
        "",
        f"🔄 {status}",
    ])


async def _try_edit(context, chat_id, message_id, text, keyboard=None):
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


async def send_dm_card(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    player_id: int,
    player_name: str,
    opponent_name: str,
    is_my_turn_to_call: bool,
    need_to_mark: bool,
) -> bool:
    """Send or update the interactive card in the player's DM. Returns True on success."""
    card = await db.get_card(room["id"], player_id)
    if not card:
        return False

    called = json.loads(room["called_numbers"])
    last_called = room.get("last_called_number")

    text = build_dm_card_text(
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
    keyboard = build_dm_card_keyboard(
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
                return True
            except BadRequest:
                pass

        msg = await context.bot.send_message(
            chat_id=player_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await db.update_card_message_id(card["id"], msg.message_id)
        return True
    except (Forbidden, BadRequest):
        return False


async def update_group_turn_panel(
    context: ContextTypes.DEFAULT_TYPE,
    room: dict,
    active_player_id: int,
    active_player_name: str,
    waiting_player_name: str,
):
    """Update the group 'turn panel' message — one message per player showing who acts."""
    bot_username = context.bot.username
    phase = room.get("phase", "call")
    last_called = room.get("last_called_number")
    chat_id = room["chat_id"]

    active_text = build_group_turn_text(
        room["room_number"], active_player_name, waiting_player_name, phase, last_called
    )
    active_kb = build_group_turn_keyboard(bot_username)
    waiting_text = build_group_waiting_text(room["room_number"], active_player_name)

    for pid in (room["player1_id"], room["player2_id"]):
        card = await db.get_card(room["id"], pid)
        if not card or not card.get("card_message_id"):
            continue
        is_active = pid == active_player_id
        text = active_text if is_active else waiting_text
        kb = active_kb if is_active else None
        await _try_edit(context, chat_id, card["card_message_id"], text, kb)


async def update_live_message(context, room, p1, p2):
    if not room.get("live_message_id"):
        return
    try:
        await context.bot.edit_message_text(
            chat_id=room["chat_id"],
            message_id=room["live_message_id"],
            text=build_live_message(room, p1, p2),
            parse_mode="HTML",
        )
    except BadRequest:
        pass


async def handle_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return

    room_id = int(parts[1])
    number = int(parts[2])
    player_id = query.from_user.id

    # Only valid in DM context
    if query.message.chat.type != "private":
        await query.answer("🚫 Interact with your card in the private DM!", show_alert=True)
        return

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
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)

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
        marker_id = room["player2_id"] if player_id == room["player1_id"] else room["player1_id"]
        marker_name = p2_name if player_id == room["player1_id"] else p1_name

        await asyncio.gather(
            update_live_message(context, room, p1, p2),
            send_dm_card(context, room, player_id, caller_name,
                         marker_name, False, False),
            send_dm_card(context, room, marker_id, marker_name,
                         caller_name, False, True),
        )
        await update_group_turn_panel(context, room, marker_id, marker_name, caller_name)

    elif phase == "mark":
        marker_id = (
            room["player2_id"] if caller_id == room["player1_id"] else room["player1_id"]
        )

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

        marker_name = p1_name if player_id == room["player1_id"] else p2_name
        caller_name = p2_name if player_id == room["player1_id"] else p1_name
        other_id = room["player2_id"] if player_id == room["player1_id"] else room["player1_id"]

        await asyncio.gather(
            update_live_message(context, room, p1, p2),
            send_dm_card(context, room, player_id, marker_name,
                         caller_name, True, False),
            send_dm_card(context, room, other_id, caller_name,
                         marker_name, False, False),
        )
        await update_group_turn_panel(context, room, player_id, marker_name, caller_name)


async def handle_bingo_win(context, room, winner_id, p1, p2, called):
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

    for pid in (room["player1_id"], room["player2_id"]):
        card = await db.get_card(room["id"], pid)
        result = "🏆 You won! +500 coins added." if pid == winner_id else "😔 You lost. Better luck next time!"
        final_dm = (
            f"🏁 <b>Game Over — Room #{room['room_number']}</b>\n\n"
            f"{result}\n"
            f"Winner: <b>{winner_name}</b>"
        )
        try:
            if card and card.get("card_message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=pid,
                        message_id=card["card_message_id"],
                        text=final_dm,
                        parse_mode="HTML",
                    )
                except BadRequest:
                    await context.bot.send_message(chat_id=pid, text=final_dm, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=pid, text=final_dm, parse_mode="HTML")
        except (Forbidden, BadRequest):
            pass

        for pid2 in (room["player1_id"], room["player2_id"]):
            panel_card = await db.get_card(room["id"], pid2)
            if panel_card and panel_card.get("card_message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=room["chat_id"],
                        message_id=panel_card["card_message_id"],
                        text=f"🏁 <b>Game Over — Room #{room['room_number']}</b>\n\nWinner: <b>{winner_name}</b>",
                        parse_mode="HTML",
                    )
                except BadRequest:
                    pass
        break


async def start_game_countdown(context, room_id, chat_id, p1, p2, room_message_id):
    p1_name = display_name_from_db(p1)
    p2_name = display_name_from_db(p2)
    bot_username = context.bot.username

    for count in range(5, 0, -1):
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=room_message_id,
                text=(
                    f"🎉 <b>Opponent Found!</b>\n\n"
                    f"👤 Player 1: {p1_name}\n"
                    f"👤 Player 2: {p2_name}\n\n"
                    f"⏳ Game starts in <b>{count}...</b>"
                ),
                parse_mode="HTML",
            )
        except BadRequest:
            pass
        await asyncio.sleep(1)

    await db.create_card(room_id, p1["telegram_id"], generate_card())
    await db.create_card(room_id, p2["telegram_id"], generate_card())
    await db.update_room(room_id,
                         current_turn=p1["telegram_id"],
                         phase="call",
                         last_called_number=None,
                         called_numbers="[]")

    room = await db.get_room(room_id)

    live_text = build_live_message(room, p1, p2)
    try:
        live_msg = await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=room_message_id,
            text=live_text,
            parse_mode="HTML",
        )
    except BadRequest:
        live_msg = await context.bot.send_message(
            chat_id=chat_id, text=live_text, parse_mode="HTML"
        )
    await db.update_room(room_id, live_message_id=live_msg.message_id)
    room = await db.get_room(room_id)

    dm_failed = []
    for pid, pname, oname, is_caller in [
        (p1["telegram_id"], p1_name, p2_name, True),
        (p2["telegram_id"], p2_name, p1_name, False),
    ]:
        card = await db.get_card(room_id, pid)
        text = build_dm_card_text(
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
        keyboard = build_dm_card_keyboard(
            room_id=room_id,
            numbers=card["numbers"],
            marked=card["marked_numbers"],
            called_numbers=[],
            last_called=None,
            is_my_turn_to_call=is_caller,
            need_to_mark=False,
        )
        try:
            msg = await context.bot.send_message(
                chat_id=pid,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            await db.update_card_message_id(card["id"], msg.message_id)
        except (Forbidden, BadRequest):
            dm_failed.append(pname)

    # Send group turn-panel messages (one per player, shows "open my card" button)
    for pid, pname, oname, is_caller in [
        (p1["telegram_id"], p1_name, p2_name, True),
        (p2["telegram_id"], p2_name, p1_name, False),
    ]:
        if is_caller:
            text = build_group_turn_text(room["room_number"], pname, oname, "call", None)
            kb = build_group_turn_keyboard(bot_username)
        else:
            text = build_group_waiting_text(room["room_number"], p1_name)
            kb = None

        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
        card = await db.get_card(room_id, pid)
        await db.update_card_message_id(card["id"], msg.message_id)

    if dm_failed:
        names = ", ".join(dm_failed)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ Could not send private cards to: <b>{names}</b>\n\n"
                f"These players must start a DM with the bot first:\n"
                f"👉 Tap here → @{bot_username} then press <b>Start</b>"
            ),
            parse_mode="HTML",
        )
