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
    return (
        f"🃏 Room #{room_number} — Your Card\n\n"
        f"{grid}\n\n"
        f"Lines: {completed_lines}/{LINES_TO_WIN}  {bingo}"
    )


def build_dm_card_text(
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
    bingo = get_bingo_status(completed_lines)
    called_str = " • ".join(str(n) for n in called_numbers) if called_numbers else "None"

    if is_my_turn_to_call:
        action = "🎯 <b>Your turn!</b> Tap a number below to call it."
    elif need_to_mark:
        action = f"⚡ <b>Mark number {last_called}!</b> Find and tap it on your card."
    else:
        action = f"⏳ Waiting for <b>{opponent_name}</b>..."

    rows_text = []
    for r in range(5):
        parts = []
        for c in range(5):
            num = numbers[r * 5 + c]
            if num in marked:
                parts.append(f"✅{num:2}")
            elif num == last_called and need_to_mark:
                parts.append(f"⚡{num:2}")
            else:
                parts.append(f"  {num:2}")
        rows_text.append("  ".join(parts))
    grid = "\n".join(rows_text)

    return (
        f"🎮 <b>Velocity Bingo — Room #{room_number}</b>\n"
        f"👤 You: <b>{player_name}</b>  |  👥 Opponent: <b>{opponent_name}</b>\n"
        f"────────────────────\n"
        f"📋 Called: {called_str}\n"
        f"🔤 {bingo}  ✅ Lines: {completed_lines}/{LINES_TO_WIN}\n"
        f"────────────────────\n\n"
        f"<code>{grid}</code>\n\n"
        f"{action}"
    )


def build_dm_card_keyboard(
    room_id: int,
    numbers: List[int],
    marked: List[int],
    called_numbers: List[int],
    last_called: Optional[int],
    is_my_turn_to_call: bool,
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


def build_group_turn_text(room_number: int, player_name: str, opponent_name: str,
                          phase: str, last_called: Optional[int]) -> str:
    if phase == "call":
        return (
            f"🎯 <b>{player_name}</b> — it's your turn to call a number!\n"
            f"Tap <b>Open My Card</b> to see your numbers and make your move."
        )
    else:
        return (
            f"⚡ <b>{player_name}</b> — mark number <b>{last_called}</b>!\n"
            f"Tap <b>Open My Card</b> to mark it on your private card."
        )


def build_group_turn_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📩 Open My Card", url=f"https://t.me/{bot_username}")
    ]])


def build_group_waiting_text(room_number: int, waiting_name: str) -> str:
    return f"⏳ <b>{waiting_name}</b> is making their move... Please wait."
