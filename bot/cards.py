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
        if i < completed_lines:
            letters += f"✅{letter} "
        else:
            letters += f"❌{letter} "
    return letters.strip()


def build_card_keyboard(
    room_id: int,
    numbers: List[int],
    marked: List[int],
    called_numbers: List[int],
    last_called: Optional[int],
    is_my_turn_to_call: bool,
    need_to_mark: bool,
) -> InlineKeyboardMarkup:
    rows = []
    for row_idx in range(5):
        row = []
        for col_idx in range(5):
            num = numbers[row_idx * 5 + col_idx]
            if num in marked:
                label = f"✅{num}"
            elif num == last_called and need_to_mark:
                label = f"⚡{num}"
            else:
                label = str(num)
            row.append(
                InlineKeyboardButton(label, callback_data=f"card:{room_id}:{num}")
            )
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def build_card_text(
    room_number: int,
    player_name: str,
    opponent_name: str,
    numbers: List[int],
    marked: List[int],
    completed_lines: int,
    called_numbers: List[int],
    is_my_turn_to_call: bool,
    need_to_mark: bool,
    last_called: Optional[int],
) -> str:
    bingo_status = get_bingo_status(completed_lines)
    called_str = " • ".join(str(n) for n in called_numbers) if called_numbers else "None"

    if is_my_turn_to_call:
        turn_line = "🎯 Your turn! Tap a number to call it."
    elif need_to_mark:
        turn_line = f"⚡ Mark number <b>{last_called}</b> on your card!"
    else:
        turn_line = f"⏳ Waiting for {opponent_name} to mark..."

    lines = [
        f"🎮 <b>Velocity Bingo — Room #{room_number}</b>",
        "",
        f"👤 You: <b>{player_name}</b>",
        f"👥 Opponent: <b>{opponent_name}</b>",
        "",
        f"📋 <b>Called Numbers:</b> {called_str}",
        "",
        f"🔤 Bingo Progress: {bingo_status}",
        f"✅ Lines: <b>{completed_lines}/{LINES_TO_WIN}</b>",
        "",
        turn_line,
    ]
    return "\n".join(lines)
