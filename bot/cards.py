import random
from typing import List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from models import ALL_LINES, BINGO_LETTERS, LINES_TO_WIN


def generate_card() -> List[int]:
    numbers = list(range(1, 26))
    random.shuffle(numbers)
    return numbers


def count_completed_lines(numbers: List[int], marked: List[int]) -> int:
    count = 0
    for line in ALL_LINES:
        if all(numbers[i] in marked for i in line):
            count += 1
    return count


def get_bingo_status(completed_lines: int) -> str:
    letters = ""
    for i, letter in enumerate(BINGO_LETTERS):
        letters += f"✅{letter} " if i < completed_lines else f"❌{letter} "
    return letters.strip()


def build_popup_card_text(
    room_number: int,
    numbers: List[int],
    marked: List[int],
    completed_lines: int,
) -> str:
    rows = []
    for r in range(5):
        row_parts = []
        for c in range(5):
            num = numbers[r * 5 + c]
            if num in marked:
                row_parts.append(f"✅{num:2d}")
            else:
                row_parts.append(f"  {num:2d}")
        rows.append(" ".join(row_parts))
    grid = "\n".join(rows)

    bingo = ""
    for i, letter in enumerate(BINGO_LETTERS):
        bingo += f"{'✅' if i < completed_lines else '❌'}{letter} "

    return (
        f"🃏 Room #{room_number} — Your Card\n\n"
        f"{grid}\n\n"
        f"Lines: {completed_lines}/{LINES_TO_WIN}  {bingo.strip()}"
    )


def build_locked_text(room_number: int, player_name: str) -> str:
    return (
        f"🔒 <b>{player_name}'s Card</b> — Room #{room_number}\n\n"
        f"Tap the button below to privately view your numbers.\n"
        f"Only you can see your card."
    )


def build_locked_keyboard(room_id: int, player_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 Peek at My Card", callback_data=f"view_card:{room_id}:{player_id}")]
    ])


def build_active_text(
    room_number: int,
    player_name: str,
    opponent_name: str,
    completed_lines: int,
    called_numbers: List[int],
    is_my_turn_to_call: bool,
    need_to_mark: bool,
    last_called: Optional[int],
) -> str:
    bingo_status = get_bingo_status(completed_lines)
    called_str = " • ".join(str(n) for n in called_numbers) if called_numbers else "None"

    if is_my_turn_to_call:
        action_line = "🎯 <b>Your turn!</b> Tap a number to call it."
    elif need_to_mark:
        action_line = f"⚡ <b>Mark number {last_called}!</b> Tap it on your card below."
    else:
        action_line = f"⏳ Waiting for <b>{opponent_name}</b>..."

    return (
        f"🎮 <b>Room #{room_number}</b> — {player_name}'s Card\n"
        f"────────────────────\n"
        f"📋 Called: {called_str}\n"
        f"🔤 {bingo_status}  ✅ Lines: {completed_lines}/{LINES_TO_WIN}\n"
        f"────────────────────\n"
        f"{action_line}"
    )


def build_active_keyboard(
    room_id: int,
    numbers: List[int],
    marked: List[int],
    last_called: Optional[int],
    need_to_mark: bool,
) -> InlineKeyboardMarkup:
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            num = numbers[r * 5 + c]
            if num in marked:
                label = f"✅{num}"
            elif num == last_called and need_to_mark:
                label = f"⚡{num}"
            else:
                label = str(num)
            row.append(InlineKeyboardButton(label, callback_data=f"card:{room_id}:{num}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)
