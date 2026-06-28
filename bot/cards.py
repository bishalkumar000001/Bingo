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
    return " ".join(
        f"✅{letter}" if i < completed_lines else f"❌{letter}"
        for i, letter in enumerate(BINGO_LETTERS)
    )


def build_popup_card_text(
    room_number: int,
    numbers: List[int],
    marked: List[int],
    completed_lines: int,
) -> str:
    rows = []
    for r in range(5):
        parts = []
        for c in range(5):
            num = numbers[r * 5 + c]
            parts.append(f"✅{num:2}" if num in marked else f"  {num:2}")
        rows.append("  ".join(parts))
    grid = "\n".join(rows)
    bingo = " ".join(
        f"✅{l}" if i < completed_lines else f"❌{l}"
        for i, l in enumerate(BINGO_LETTERS)
    )
    return f"🃏 Room #{room_number} — Your Card\n\n{grid}\n\nLines: {completed_lines}/{LINES_TO_WIN}  {bingo}"


def _peek_button(room_id: int, player_id: int) -> InlineKeyboardButton:
    return InlineKeyboardButton("👁 Peek at My Card", callback_data=f"view_card:{room_id}:{player_id}")


def build_locked_text(room_number: int, player_name: str, completed_lines: int) -> str:
    bingo = get_bingo_status(completed_lines)
    return (
        f"🔒 <b>{player_name}'s Card</b> — Room #{room_number}\n"
        f"Lines: {completed_lines}/{LINES_TO_WIN}  {bingo}\n\n"
        f"⏳ Waiting for opponent's turn..."
    )


def build_locked_keyboard(room_id: int, player_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_peek_button(room_id, player_id)]])


def build_call_text(room_number: int, player_name: str, completed_lines: int, called_count: int) -> str:
    bingo = get_bingo_status(completed_lines)
    return (
        f"🎯 <b>{player_name} — YOUR TURN!</b> — Room #{room_number}\n"
        f"Lines: {completed_lines}/{LINES_TO_WIN}  {bingo}\n\n"
        f"Tap any number below to call it.\n"
        f"👁 Peek at your card to plan your move!"
    )


def build_call_keyboard(room_id: int, player_id: int, called_numbers: List[int]) -> InlineKeyboardMarkup:
    uncalled = [n for n in range(1, 26) if n not in called_numbers]
    rows = []
    chunk = 5
    for i in range(0, len(uncalled), chunk):
        row = [
            InlineKeyboardButton(str(n), callback_data=f"card:{room_id}:{n}")
            for n in uncalled[i:i + chunk]
        ]
        rows.append(row)
    rows.append([_peek_button(room_id, player_id)])
    return InlineKeyboardMarkup(rows)


def build_mark_text(room_number: int, player_name: str, completed_lines: int, last_called: int) -> str:
    bingo = get_bingo_status(completed_lines)
    return (
        f"⚡ <b>{player_name} — MARK {last_called}!</b> — Room #{room_number}\n"
        f"Lines: {completed_lines}/{LINES_TO_WIN}  {bingo}\n\n"
        f"Number <b>{last_called}</b> was called. Mark it on your card!"
    )


def build_mark_keyboard(room_id: int, player_id: int, last_called: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Mark {last_called}", callback_data=f"card:{room_id}:{last_called}")],
        [_peek_button(room_id, player_id)],
    ])
