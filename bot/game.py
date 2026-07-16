import asyncio
import io
from collections import defaultdict
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
from models import WIN_COINS, LINES_TO_WIN, LOGGER_GROUP_ID, SUPPORT_CHANNEL
from utils import display_name_from_db, format_called_numbers

ROOM_LOCKS = defaultdict(asyncio.Lock)


def _msg_link(chat_id: int, message_id: int) -> str:
    cid = str(chat_id)
    link_id = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{link_id}/{message_id}"


async def _log(context, text: str):
    if not LOGGER_GROUP_ID:
        return
    try:
        await context.bot.send_message(LOGGER_GROUP_ID, text, parse_mode="HTML")
    except Exception:
        pass


async def _try_pin(context, chat_id: int, message_id: int):
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id, message_id=message_id, disable_notification=True
        )
    except (BadRequest, Forbidden):
        pass


async def _try_unpin(context, chat_id: int, message_id: int):
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
    except (BadRequest, Forbidden):
        pass


def _open_card_kb(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📩 Open My Card", url=f"https://t.me/{bot_username}")
    ]])


def build_live_message(room: dict, p1: dict, p2: dict) -> str:
    called = room.get("called_numbers") or []
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
    for _ in range(3):
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return True
        except BadRequest as e:
            if "Message is not modified" in str(e):
                return True

            await asynsio.sleep(0.5)

        except Exception:
            await asynsio.sleep(0.5)
            
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
    card = await db.get_card(room["id"], player_id)
    if not card:
        return False

    called = room.get("called_numbers") or []
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
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    return True
                        pass
        msg = await context.bot.send_message(
            chat_id=player_id, text=text, reply_markup=keyboard, parse_mode="HTML"
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
    bot_username = context.bot.username
    phase = room.get("phase", "call")
    last_called = room.get("last_called_number")
    chat_id = room["chat_id"]

    active_text = build_group_turn_text(
        room["room_number"], active_player_name, waiting_player_name, phase, last_called
    )
    active_kb = build_group_turn_keyboard(bot_username, SUPPORT_CHANNEL)

    panel_message_id = room.get("group_panel_message_id")
    if panel_message_id:
        if await _try_edit(context, chat_id, panel_message_id, active_text, active_kb):
            return

    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=active_text,
            reply_markup=active_kb,
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        return

    await db.update_room(room["id"], group_panel_message_id=msg.message_id)


async def update_live_message(context, room, p1, p2):
    text = build_live_message(room, p1, p2)
    if not room.get("live_message_id"):
        if await _try_edit(
            context,
            room["chat_id"],
            room["live_message_id"],
            text,
        ):
            return
    try:
        msg = await context.bot.edit_message_text(
            chat_id=room["chat_id"],
            text=text,
            parse_mode="HTML",
        )
    except BadRequest:
        pass


ALL_LINES = [
    [0, 1, 2, 3, 4],
    [5, 6, 7, 8, 9],
    [10, 11, 12, 13, 14],
    [15, 16, 17, 18, 19],
    [20, 21, 22, 23, 24],
    [0, 5, 10, 15, 20],
    [1, 6, 11, 16, 21],
    [2, 7, 12, 17, 22],
    [3, 8, 13, 18, 23],
    [4, 9, 14, 19, 24],
    [0, 6, 12, 18, 24],
    [4, 8, 12, 16, 20],
]


def _render_bingo_card_text(numbers: list, marked: list) -> str:
    """
    Render winner's 5×5 bingo card as an emoji grid — no libraries needed.
    🟥 = part of a winning line  🟩 = marked  ⬜ = not yet marked
    """
    winning_indices: set = set()
    for line in ALL_LINES:
        if all(numbers[i] in marked for i in line):
            winning_indices.update(line)

    lines_out = []
    for row in range(5):
        parts = []
        for col in range(5):
            idx = row * 5 + col
            num = numbers[idx]
            if idx in winning_indices:
                icon = "🟥"
            elif num in marked:
                icon = "🟩"
            else:
                icon = "⬜"
            parts.append(f"{icon}{num:>2}")
        lines_out.append("  ".join(parts))

    grid = "\n".join(lines_out)
    return (
        f"🎴 <b>Winner's Card:</b>\n"
        f"<code>{grid}</code>\n"
        f"🟥 winning line  🟩 marked  ⬜ open\n\n"
    )


def _render_bingo_card_image(
    numbers: list,
    marked: list,
) -> Optional[io.BytesIO]:
    """
    Render the winner's bingo card as a PNG image.
    - 5x5 dark cells with numbers
    - Green background + checkmark on marked cells
    - Red lines through every completed winning line
    Compatible with Pillow 7+ (no rounded_rectangle dependency).
    Returns BytesIO PNG or None if Pillow is unavailable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    try:
        COLS = 5
        CELL = 90
        GAP = 8
        PAD = 20
        IMG_SIZE = PAD * 2 + COLS * CELL + (COLS - 1) * GAP

        BG_COLOR = (18, 18, 28)
        CELL_DARK = (45, 32, 24)
        CELL_MARKED = (28, 68, 28)
        NUM_COLOR = (230, 230, 230)
        CHECK_COLOR = (80, 220, 80)
        LINE_COLOR = (220, 30, 30)
        LINE_W = 7

        img = Image.new("RGB", (IMG_SIZE, IMG_SIZE), BG_COLOR)
        draw = ImageDraw.Draw(img)

        font_num = None
        font_small = None
        for font_path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            try:
                font_num = ImageFont.truetype(font_path, 28)
                font_small = ImageFont.truetype(font_path, 18)
                break
            except Exception:
                continue
        if font_num is None:
            font_num = ImageFont.load_default()
            font_small = font_num

        def cell_rect(idx):
            row, col = divmod(idx, COLS)
            x = PAD + col * (CELL + GAP)
            y = PAD + row * (CELL + GAP)
            return x, y, x + CELL, y + CELL

        def cell_center(idx):
            x0, y0, x1, y1 = cell_rect(idx)
            return (x0 + x1) // 2, (y0 + y1) // 2

        def draw_cell(idx, color):
            x0, y0, x1, y1 = cell_rect(idx)
            try:
                draw.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=color)
            except AttributeError:
                draw.rectangle([x0, y0, x1, y1], fill=color)

        for idx in range(25):
            is_marked = numbers[idx] in marked
            draw_cell(idx, CELL_MARKED if is_marked else CELL_DARK)

            cx, cy = cell_center(idx)
            num_str = str(numbers[idx])

            if is_marked:
                try:
                    draw.text((cx, cy - 14), "✓", fill=CHECK_COLOR,
                              font=font_small, anchor="mm")
                    draw.text((cx, cy + 16), num_str, fill=NUM_COLOR,
                              font=font_small, anchor="mm")
                except TypeError:
                    draw.text((cx - 10, cy - 24), "✓", fill=CHECK_COLOR, font=font_small)
                    draw.text((cx - 10, cy + 4), num_str, fill=NUM_COLOR, font=font_small)
            else:
                try:
                    draw.text((cx, cy), num_str, fill=NUM_COLOR,
                              font=font_num, anchor="mm")
                except TypeError:
                    draw.text((cx - 10, cy - 14), num_str, fill=NUM_COLOR, font=font_num)

        completed_lines = [
            line for line in ALL_LINES
            if all(numbers[i] in marked for i in line)
        ]
        for line in completed_lines:
            start = cell_center(line[0])
            end = cell_center(line[-1])
            draw.line([start, end], fill=LINE_COLOR, width=LINE_W)

        out = io.BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        return out
    except Exception:
        return None


async def handle_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return

    room_id = parts[1]
    number = int(parts[2])
    player_id = query.from_user.id

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

async with ROOM_LOCKS[room_id]:
    room = await db.get_room(room_id)
    
    called = room.get("called_numbers") or []
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

        called = called + [number]
        await db.update_room(room_id,
                             called_numbers=called,
                             last_called_number=number,
                             phase="mark")

        card = await db.get_card(room_id, player_id)
        new_lines = count_completed_lines(card["numbers"], card["marked_numbers"] + [number])
        await db.mark_number(card["id"], number, new_lines)

        if new_lines >= LINES_TO_WIN:
            await handle_bingo_win(context, room, player_id, p1, p2, called)
            return

        caller_name = display_name_from_db(p1 if room["player1_id"] == player_id else p2)

        old_call = room.get("last_call_message_id")

        if old_call:
            try:
                await context.bot.delete_message(
                    chat_id=room["chat_id"],
                    message_id=old_call,
                )
            except Exception:
                pass

        msg = await context.bot.send_message(
            chat_id=room["chat_id"],
            text=f"🎲 <b>Room #{room['room_number']}</b> — {caller_name} called <b>{number}</b>!",
            reply_markup=_open_card_kb(context.bot.username),
            parse_mode="HTML",
        )

        await db.update_room(
            room_id,
            last_call_message_id=msg.message_id,
        )

        room = await db.get_room(room_id)
        marker_id = room["player2_id"] if player_id == room["player1_id"] else room["player1_id"]
        marker_name = p2_name if player_id == room["player1_id"] else p1_name

        await asyncio.gather(
            update_live_message(context, room, p1, p2),
            send_dm_card(context, room, player_id, caller_name, marker_name, False, False),
            send_dm_card(context, room, marker_id, marker_name, caller_name, False, True),
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
            send_dm_card(context, room, player_id, marker_name, caller_name, True, False),
            send_dm_card(context, room, other_id, caller_name, marker_name, False, False),
        )
        await update_group_turn_panel(context, room, player_id, marker_name, caller_name)


async def handle_bingo_win(context, room, winner_id, p1, p2, called):
    chat_id = room["chat_id"]
    loser_id = room["player2_id"] if winner_id == room["player1_id"] else room["player1_id"]
    await db.finish_room(room["id"])
    await asyncio.gather(
        award_winner(winner_id, chat_id),
        record_loss(loser_id, chat_id),
    )

    winner = p1 if winner_id == room["player1_id"] else p2
    loser = p2 if winner_id == room["player1_id"] else p1
    winner_name = display_name_from_db(winner)
    loser_name = display_name_from_db(loser)

    win_text = (
        f"🏆 <b>BINGO!</b>\n\n"
        f"🥇 Winner: <b>{winner_name}</b>\n"
        f"😔 Loser: <b>{loser_name}</b>\n"
        f"🏠 Room: <b>#{room['room_number']}</b>\n"
        f"💰 Reward: <b>+{WIN_COINS} Coins</b>\n\n"
        f"📋 Numbers called: {format_called_numbers(called)}"
    )

    rematch_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Rematch!", callback_data=f"rematch:{room['id']}")
    ]])

    winner_card = await db.get_card(room["id"], winner_id)
    card_image = None
    card_text = ""
    if winner_card:
        # Merge DB marked numbers with every called number that appears on the
        # winner's card — this guarantees the last click is always visible even
        # if the async DB write hasn't settled yet.
        card_numbers_set = set(winner_card["numbers"])
        effective_marked = list(
            set(winner_card.get("marked_numbers", [])) |
            {n for n in called if n in card_numbers_set}
        )
        card_image = _render_bingo_card_image(
            numbers=winner_card["numbers"],
            marked=effective_marked,
        )
        card_text = _render_bingo_card_text(
            numbers=winner_card["numbers"],
            marked=effective_marked,
        )

    live_mid = room.get("live_message_id")

    async def _send_result_to_group():
        if live_mid:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=live_mid)
            except (BadRequest, Forbidden):
                pass

        if card_image is not None:
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=card_image,
                    caption=win_text,
                    reply_markup=rematch_kb,
                    parse_mode="HTML",
                )
                return
            except Exception:
                if card_image:
                    card_image.seek(0)

        full_text = card_text + win_text
        await context.bot.send_message(
            chat_id=chat_id, text=full_text, reply_markup=rematch_kb, parse_mode="HTML"
        )

    await _send_result_to_group()

    if live_mid:
        await _try_unpin(context, chat_id, live_mid)

    for pid in (room["player1_id"], room["player2_id"]):
        card = await db.get_card(room["id"], pid)
        is_winner = pid == winner_id
        result = "🏆 You won! +500 coins added." if is_winner else "😔 You lost. Better luck next time!"
        final_dm = (
            f"🏁 <b>Game Over — Room #{room['room_number']}</b>\n\n"
            f"{result}\n"
            f"🥇 Winner: <b>{winner_name}</b>\n"
            f"😔 Loser: <b>{loser_name}</b>"
        )
        try:
            if card and card.get("card_message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=pid, message_id=card["card_message_id"],
                        text=final_dm, parse_mode="HTML",
                    )
                except BadRequest:
                    await context.bot.send_message(chat_id=pid, text=final_dm, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=pid, text=final_dm, parse_mode="HTML")
        except (Forbidden, BadRequest):
            pass

    for pid in (room["player1_id"], room["player2_id"]):
        panel_card = await db.get_card(room["id"], pid)
        if panel_card and panel_card.get("card_message_id"):
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=panel_card["card_message_id"],
                    text=(
                        f"🏁 <b>Game Over — Room #{room['room_number']}</b>\n\n"
                        f"🥇 Winner: <b>{winner_name}</b>\n"
                        f"😔 Loser: <b>{loser_name}</b>"
                    ),
                    parse_mode="HTML",
                )
            except BadRequest:
                pass


async def handle_rematch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    old_room_id = query.data.split(":")[1]

    old_room = await db.get_room(old_room_id)
    if not old_room:
        await query.answer("Original room not found.", show_alert=True)
        return

    if user.id not in (old_room["player1_id"], old_room["player2_id"]):
        await query.answer("🚫 Only players from this match can rematch!", show_alert=True)
        return

    if old_room["status"] not in ("finished", "cancelled"):
        await query.answer("Game isn't over yet!", show_alert=True)
        return

    p1_id = old_room["player1_id"]
    p2_id = old_room["player2_id"]
    chat_id = old_room["chat_id"]

    p1 = await db.get_user(p1_id)
    p2 = await db.get_user(p2_id)

    if not p1 or not p2:
        await query.answer("A player is no longer registered.", show_alert=True)
        return

    if await db.is_player_in_active_room(p1_id):
        await query.answer(
            f"{display_name_from_db(p1)} is already in another active match!",
            show_alert=True,
        )
        return

    if await db.is_player_in_active_room(p2_id):
        await query.answer(
            f"{display_name_from_db(p2)} is already in another active match!",
            show_alert=True,
        )
        return

    from models import MAX_ROOMS_PER_CHAT
    active_rooms = await db.get_active_rooms_in_chat(chat_id)
    if len(active_rooms) >= MAX_ROOMS_PER_CHAT:
        await query.answer(
            f"This group already has {MAX_ROOMS_PER_CHAT} active rooms. Wait for one to finish!",
            show_alert=True,
        )
        return

    await query.answer("🔄 Starting rematch!")

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest:
        pass

    room_number = await db.get_next_room_number(chat_id)
    placeholder = await context.bot.send_message(
        chat_id=chat_id, text="🔄 Setting up rematch..."
    )

    new_room_id = await db.create_room(
        chat_id=chat_id,
        room_number=room_number,
        player1_id=p1_id,
        room_message_id=placeholder.message_id,
    )
    await db.join_room(new_room_id, p2_id)

    asyncio.create_task(
        start_game_countdown(
            context,
            room_id=new_room_id,
            chat_id=chat_id,
            p1=p1,
            p2=p2,
            room_message_id=placeholder.message_id,
        )
    )


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
                         called_numbers=[])

    room = await db.get_room(room_id)

    live_text = build_live_message(room, p1, p2)
    try:
        live_msg = await context.bot.edit_message_text(
            chat_id=chat_id, message_id=room_message_id, text=live_text, parse_mode="HTML"
        )
    except BadRequest:
        live_msg = await context.bot.send_message(
            chat_id=chat_id, text=live_text, parse_mode="HTML"
        )
    await db.update_room(room_id, live_message_id=live_msg.message_id)
    room = await db.get_room(room_id)

    await _try_pin(context, chat_id, live_msg.message_id)

    try:
        chat_info = await context.bot.get_chat(chat_id)
        chat_title = chat_info.title or str(chat_id)
    except Exception:
        chat_title = str(chat_id)

    await _log(
        context,
        f"🎮 <b>Game Started</b>\n\n"
        f"<b>CHAT:</b> <code>{chat_id}</code> | {chat_title}\n"
        f"<b>USER:</b> <code>{p1['telegram_id']}</code> | {p1_name}\n"
        f"<b>VS:</b> <code>{p2['telegram_id']}</code> | {p2_name}\n"
        f"<b>MESSAGE LINK:</b> {_msg_link(chat_id, live_msg.message_id)}"
    )

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
                chat_id=pid, text=text, reply_markup=keyboard, parse_mode="HTML"
            )
            await db.update_card_message_id(card["id"], msg.message_id)
        except (Forbidden, BadRequest):
            dm_failed.append(pname)

    panel_text = build_group_turn_text(room["room_number"], p1_name, p2_name, "call", None)
    panel_kb = build_group_turn_keyboard(bot_username, SUPPORT_CHANNEL)
    panel_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=panel_text,
        reply_markup=panel_kb,
        parse_mode="HTML",
    )
    await db.update_room(room_id, group_panel_message_id=panel_msg.message_id)

    if dm_failed:
        names = ", ".join(dm_failed)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ Could not send private cards to: <b>{names}</b>\n\n"
                f"These players must start a DM with the bot first:\n"
                f"👉 @{bot_username} → press <b>Start</b>"
            ),
            parse_mode="HTML",
        )
