"""Knockout tournament orchestration for Velocity Bingo.

Tournament matches deliberately use the normal room/card engine.  This module
only owns registration, bracket state, round advancement, and tournament
payouts; the game rules stay in game.py.
"""

import asyncio
import html
import os
import random
from collections import defaultdict
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import database as db
from models import OWNER_IDS
from utils import create_background_task, display_name_from_db

MAX_PLAYERS = 64
MIN_PLAYERS = 2


def _concurrency_limit() -> int:
    try:
        configured = int(os.environ.get("TOURNAMENT_MAX_CONCURRENT_MATCHES", "8"))
    except (TypeError, ValueError):
        configured = 8
    return max(1, min(16, configured))


MAX_CONCURRENT_MATCHES = _concurrency_limit()
DEFAULT_PRIZE_COINS = 5000
DEFAULT_RULES = "Single elimination • 5 completed lines wins • Forfeit gives the win to your opponent"

TOURNAMENT_LOCKS = defaultdict(asyncio.Lock)


def _owner_ok(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id in OWNER_IDS)


def _esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


def _name(user: Optional[dict]) -> str:
    return display_name_from_db(user) if user else "Player"


def _parse_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value.strip())))
    except (TypeError, ValueError):
        return default


def _active_keyboard(tournament_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏆 Join", callback_data=f"tournament_join:{tournament_id}"),
            InlineKeyboardButton("↩ Leave", callback_data=f"tournament_leave:{tournament_id}"),
        ],
        [InlineKeyboardButton("📊 Status", callback_data=f"tournament_status:{tournament_id}")],
    ])


def _registration_text(tournament: dict, count: Optional[int] = None) -> str:
    count = count if count is not None else len(tournament.get("players", []))
    custom_text = tournament.get("announcement_text")
    if custom_text:
        max_players = int(tournament.get("max_players", MAX_PLAYERS))
        fee = int(tournament.get("entry_fee", 0) or 0)
        prize = int(tournament.get("prize_coins", 0) or 0)
        replacements = {
            "{players}": str(count),
            "{max_players}": str(max_players),
            "{remaining}": str(max(0, max_players - count)),
            "{entry_fee}": f"{fee:,}",
            "{prize}": f"{prize:,}",
            "{title}": str(tournament.get("title", "")),
        }
        rendered = custom_text
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        return _esc(rendered)

    fee = int(tournament.get("entry_fee", 0) or 0)
    prize = int(tournament.get("prize_coins", 0) or 0)
    return (
        f"🏆 <b>{_esc(tournament.get('title', 'Bingo Tournament'))}</b>\n\n"
        f"👥 Players: <b>{count}/{tournament.get('max_players', MAX_PLAYERS)}</b>\n"
        f"💵 Entry fee: <b>{fee:,} Bingo Coins</b>\n"
        f"🎁 Champion prize: <b>{prize:,} Bingo Coins</b>\n"
        f"📜 Rules: {_esc(tournament.get('rules') or DEFAULT_RULES)}\n\n"
        "Press <b>Join</b> to reserve your place. Entry fees are refunded if "
        "the owner cancels the tournament."
    )


def _parse_create_args(args: list[str]):
    """Parse: /tournament create Name | max_players | entry_fee | prize | rules."""
    raw = " ".join(args[1:]).strip()
    fields = [field.strip() for field in raw.split("|")]
    title = fields[0] if fields and fields[0] else "Velocity Bingo Tournament"
    max_players = _parse_int(fields[1] if len(fields) > 1 else "", MAX_PLAYERS, MIN_PLAYERS, MAX_PLAYERS)
    entry_fee = _parse_int(fields[2] if len(fields) > 2 else "", 0, 0, 10_000_000)
    default_prize = DEFAULT_PRIZE_COINS if not entry_fee else entry_fee * max_players
    prize_coins = _parse_int(fields[3] if len(fields) > 3 else "", default_prize, 0, 100_000_000)
    rules = fields[4] if len(fields) > 4 and fields[4] else DEFAULT_RULES
    return title[:80], max_players, entry_fee, prize_coins, rules[:500]


async def _send_or_edit_registration(context, tournament: dict, message_id: Optional[int] = None):
    chat_id = int(tournament["group_id"])
    count = await db.count_tournament_players(tournament["id"])
    text = _registration_text(tournament, count)
    markup = _active_keyboard(tournament["id"])
    try:
        if message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML",
            )
            return message_id
        message = await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML"
        )
        await db.update_tournament(tournament["id"], registration_message_id=message.message_id)
        return message.message_id
    except (BadRequest, Forbidden):
        return message_id


async def cmd_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    active = await db.get_active_tournament()
    args = context.args or []
    if not args or args[0].lower() not in ("create", "new"):
        if not active:
            await update.message.reply_text(
                "No tournament is running.\n\n"
                "Create one with:\n"
                "/tournament create Name | max players | entry fee | prize coins | rules"
            )
            return
        await update.message.reply_text(
            _registration_text(active, await db.count_tournament_players(active["id"])),
            reply_markup=_active_keyboard(active["id"]),
            parse_mode="HTML",
        )
        return

    if active:
        await update.message.reply_text(
            "❌ An active tournament already exists. Use /cancel_tournament first."
        )
        return
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "❌ Run tournament creation in the group where the matches should be played."
        )
        return

    title, max_players, entry_fee, prize_coins, rules = _parse_create_args(args)
    tournament = await db.create_tournament(
        title=title,
        prize_coins=prize_coins,
        max_players=max_players,
        rules=rules,
        group_id=update.effective_chat.id,
        created_by=update.effective_user.id,
        entry_fee=entry_fee,
    )
    message_id = await _send_or_edit_registration(context, tournament)
    await db.update_tournament(tournament["id"], registration_message_id=message_id)
    await update.message.reply_text(
        f"✅ Tournament created.\n"
        f"Use /tournament_start when registration has at least {MIN_PLAYERS} players.\n"
        f"ID: <code>{tournament['id']}</code>",
        parse_mode="HTML",
    )


async def cmd_announce_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast the current registration card to known users and groups."""
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    tournament = await db.get_active_tournament()
    if not tournament or tournament.get("status") != "registration":
        await update.message.reply_text("❌ No tournament is open for registration.")
        return
    destinations = list(dict.fromkeys(
        (await db.get_all_user_ids()) + (await db.get_all_group_chat_ids())
    ))
    sent = failed = 0
    for chat_id in destinations:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=_registration_text(tournament, await db.count_tournament_players(tournament["id"])),
                reply_markup=_active_keyboard(tournament["id"]),
                parse_mode="HTML",
            )
            sent += 1
        except (BadRequest, Forbidden):
            failed += 1
        await asyncio.sleep(0.04)
    await update.message.reply_text(f"📢 Tournament announced.\n✅ Sent: {sent}\n❌ Failed: {failed}")


async def cmd_tournament_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow the owner to register known players during the registration phase."""
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    tournament = await db.get_active_tournament()
    if not tournament:
        await update.message.reply_text("❌ No active tournament.")
        return
    if tournament.get("status") != "registration":
        await update.message.reply_text(
            "❌ Players cannot be added after the tournament has started."
        )
        return

    references = list(context.args or [])
    replied_user = getattr(
        getattr(update.message, "reply_to_message", None), "from_user", None
    )
    if not references and replied_user and not replied_user.is_bot:
        references = [str(replied_user.id)]
        await db.create_user(
            replied_user.id,
            replied_user.username or "",
            replied_user.first_name or "",
        )
    if not references:
        await update.message.reply_text(
            "Usage: /tournament_add <telegram_id|@username> [more players...]\n"
            "You can also reply to a player's message with /tournament_add."
        )
        return
    if len(references) > MAX_PLAYERS:
        await update.message.reply_text(
            f"❌ You can add at most {MAX_PLAYERS} players in one command."
        )
        return

    added = []
    failed = []
    for reference in references:
        user = None
        normalized = reference.strip()
        if normalized.isdigit():
            user = await db.get_user(int(normalized))
        else:
            username = normalized.removeprefix("@").strip()
            if username:
                user = await db.find_user_by_username(username)

        if not user:
            failed.append(
                f"{_esc(reference)} — not found; ask the player to use /start first"
            )
            continue

        result = await db.join_tournament(
            tournament["id"],
            user["telegram_id"],
            user.get("username", ""),
            user.get("first_name", ""),
        )
        if result["status"] == "joined":
            added.append(
                f"{_esc(user.get('first_name') or user.get('username') or user['telegram_id'])}"
            )
        elif result["status"] == "already":
            failed.append(f"{_esc(reference)} — already registered")
        elif result["status"] == "insufficient_funds":
            failed.append(
                f"{_esc(reference)} — needs {result['fee']:,} Bingo Coins"
            )
        elif result["status"] == "full":
            failed.append(f"{_esc(reference)} — tournament is full")
        else:
            failed.append(f"{_esc(reference)} — registration is closed")

    tournament = await db.get_tournament(tournament["id"])
    if tournament and tournament.get("registration_message_id"):
        await _send_or_edit_registration(
            context, tournament, tournament["registration_message_id"]
        )
    if not tournament:
        await update.message.reply_text("❌ The tournament is no longer available.")
        return

    lines = ["🏆 <b>Manual tournament registration</b>"]
    if added:
        lines.append("✅ Added: " + ", ".join(added))
    if failed:
        lines.append("❌ Not added:\n" + "\n".join(f"• {item}" for item in failed))
    lines.append(
        f"\nPlayers: {await db.count_tournament_players(tournament['id'])}/"
        f"{tournament['max_players']}"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_tournament_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or clear the owner's custom registration announcement."""
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    tournament = await db.get_active_tournament()
    if not tournament or tournament.get("status") != "registration":
        await update.message.reply_text(
            "❌ A tournament must be open for registration to edit its message."
        )
        return

    custom_text = " ".join(context.args or []).strip()
    if not custom_text:
        source = getattr(update.message, "reply_to_message", None)
        custom_text = (
            getattr(source, "text", None)
            or getattr(source, "caption", None)
            or ""
        ).strip()
    if custom_text.lower() in {"clear", "default", "reset"}:
        custom_text = ""
    elif not custom_text:
        await update.message.reply_text(
            "Reply to the announcement you want to use and send:\n"
            "/tournament_message\n\n"
            "Or use /tournament_message followed by your text.\n"
            "Use /tournament_message clear to restore the default card.\n\n"
            "Placeholders: {players}, {max_players}, {remaining}, "
            "{entry_fee}, {prize}, {title}"
        )
        return

    if len(custom_text) > 3500:
        await update.message.reply_text(
            "❌ The custom tournament message must be 3,500 characters or fewer."
        )
        return

    await db.update_tournament(
        tournament["id"],
        announcement_text=custom_text,
    )
    tournament["announcement_text"] = custom_text
    if tournament.get("registration_message_id"):
        await _send_or_edit_registration(
            context, tournament, tournament["registration_message_id"]
        )
    await update.message.reply_text(
        "✅ Tournament announcement updated."
        if custom_text
        else "✅ Default tournament announcement restored."
    )


async def cmd_tournament_disqualify(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Disqualify a player from a queued or active tournament match."""
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    tournament = await db.get_active_tournament()
    if not tournament:
        await update.message.reply_text("❌ No active tournament.")
        return
    if tournament.get("status") != "active":
        await update.message.reply_text(
            "❌ The tournament bracket has not started yet. "
            "Use /tournament_add or let players join during registration."
        )
        return

    references = list(context.args or [])
    replied_user = getattr(
        getattr(update.message, "reply_to_message", None), "from_user", None
    )
    if not references and replied_user and not replied_user.is_bot:
        references = [str(replied_user.id)]
    if not references:
        await update.message.reply_text(
            "Usage: /tournament_disqualify <telegram_id|@username>\n"
            "You can also reply to a player's message with this command."
        )
        return

    matches = await db.get_tournament_matches(tournament["id"])
    results = []
    for reference in references[:64]:
        normalized = reference.strip()
        if normalized.isdigit():
            player = await db.get_user(int(normalized))
        else:
            player = await db.find_user_by_username(
                normalized.removeprefix("@").strip()
            )
        if not player:
            results.append(
                f"❌ {_esc(reference)} — player not found; use their Telegram ID "
                "or ask them to use /start first"
            )
            continue

        match = next(
            (
                item
                for item in matches
                if item.get("status") in ("pending", "active")
                and player["telegram_id"]
                in (item.get("player1_id"), item.get("player2_id"))
            ),
            None,
        )
        if not match:
            results.append(
                f"❌ {_esc(player.get('first_name') or reference)} — "
                "no queued or active match found"
            )
            continue

        winner_id = (
            match["player2_id"]
            if player["telegram_id"] == match["player1_id"]
            else match["player1_id"]
        )
        room = await db.get_room(match["room_id"]) if match.get("room_id") else None
        if not room:
            room = {
                "id": None,
                "tournament_id": tournament["id"],
                "tournament_match_id": match["id"],
                "chat_id": tournament["group_id"],
                "player1_id": match["player1_id"],
                "player2_id": match["player2_id"],
                "room_number": f"T{match['round']}-M{match['match_number']}",
            }

        await handle_tournament_match_finished(
            context, room, winner_id, "disqualified"
        )
        winner = await db.get_user(winner_id)
        results.append(
            f"✅ {_esc(player.get('first_name') or reference)} disqualified. "
            f"🏆 {_esc(_name(winner))} advances."
        )
        matches = await db.get_tournament_matches(tournament["id"])

    await update.message.reply_text(
        "⚔️ <b>Tournament disqualification</b>\n\n"
        + "\n".join(results),
        parse_mode="HTML",
    )


async def handle_tournament_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tournament_id = query.data.split(":", 1)[1] if ":" in query.data else None
    user = query.from_user
    await db.create_user(user.id, user.username or "", user.first_name or "")
    if not tournament_id:
        tournament = await db.get_active_tournament()
        tournament_id = tournament["id"] if tournament else None
    if not tournament_id:
        await query.answer("Registration is closed.", show_alert=True)
        return
    result = await db.join_tournament(
        tournament_id, user.id, user.username or "", user.first_name or ""
    )
    if result["status"] == "inactive":
        await query.answer("Registration is closed.", show_alert=True)
        return
    if result["status"] == "already":
        await query.answer("You are already registered.", show_alert=True)
        return
    if result["status"] == "full":
        await query.answer("This tournament is full.", show_alert=True)
        return
    if result["status"] == "insufficient_funds":
        await query.answer(
            f"You need {result['fee']:,} Bingo Coins to enter.", show_alert=True
        )
        return
    tournament = await db.get_tournament(tournament_id)
    await query.answer(f"Joined tournament! {result['count']}/{tournament['max_players']}")
    if tournament and tournament.get("registration_message_id"):
        await _send_or_edit_registration(
            context, tournament, tournament["registration_message_id"]
        )


async def handle_tournament_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tournament_id = query.data.split(":", 1)[1]
    result = await db.leave_tournament(tournament_id, query.from_user.id)
    if result["status"] == "left":
        await query.answer(
            f"You left. Refunded {result['refund']:,} Bingo Coins.", show_alert=True
        )
        tournament = await db.get_tournament(tournament_id)
        if tournament and tournament.get("registration_message_id"):
            await _send_or_edit_registration(
                context, tournament, tournament["registration_message_id"]
            )
    elif result["status"] == "not_joined":
        await query.answer("You are not registered.", show_alert=True)
    else:
        await query.answer("Registration is closed.", show_alert=True)


def _pair_players(players: list[int]) -> tuple[list[tuple[int, int]], list[int]]:
    shuffled = list(players)
    random.shuffle(shuffled)
    bracket_size = 1
    while bracket_size < len(shuffled):
        bracket_size *= 2
    byes = shuffled[: bracket_size - len(shuffled)]
    remaining = shuffled[bracket_size - len(shuffled):]
    return list(zip(remaining[::2], remaining[1::2])), byes


async def _create_round(tournament: dict, round_no: int, players: list[int]):
    pairs, byes = _pair_players(players)
    for match_number, (player1, player2) in enumerate(pairs, 1):
        await db.create_tournament_match(
            tournament["id"], round_no, match_number, player1, player2
        )
    for offset, player in enumerate(byes, len(pairs) + 1):
        await db.create_tournament_match(
            tournament["id"], round_no, offset, player, None,
            status="bye", winner_id=player,
        )
    await db.update_tournament(tournament["id"], current_round=round_no)


async def cmd_tournament_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    tournament = await db.get_active_tournament()
    if not tournament or tournament.get("status") != "registration":
        await update.message.reply_text("❌ No tournament is waiting for players.")
        return
    count = await db.count_tournament_players(tournament["id"])
    if count < MIN_PLAYERS:
        await update.message.reply_text(f"❌ Need at least {MIN_PLAYERS} players; only {count} joined.")
        return
    if not await db.start_tournament(tournament["id"]):
        await update.message.reply_text("❌ Tournament start was already processed.")
        return
    tournament = await db.get_tournament(tournament["id"])
    await _create_round(tournament, 1, tournament["players"])
    await _launch_pending_round(context, tournament["id"], 1)
    await _announce_bracket(context, tournament["id"], "🚀 Tournament started! Round 1 matches are launching.")
    await update.message.reply_text("✅ Tournament started and the knockout bracket is live.")


async def _launch_pending_round(context, tournament_id: str, round_no: int):
    tournament = await db.get_tournament(tournament_id)
    if not tournament:
        return
    matches = await db.get_tournament_matches(tournament_id, round_no)
    active_count = sum(match["status"] == "active" for match in matches)
    available_slots = max(0, MAX_CONCURRENT_MATCHES - active_count)
    for match in matches:
        if match["status"] != "pending" or available_slots <= 0:
            continue
        p1 = await db.get_user(match["player1_id"])
        p2 = await db.get_user(match["player2_id"])
        if not p1 or not p2:
            await db.finish_tournament_match(match["id"], match["player1_id"], "missing_player")
            continue
        placeholder = await context.bot.send_message(
            chat_id=tournament["group_id"],
            text=(
                f"🏆 <b>{_esc(tournament['title'])}</b>\n"
                f"⚔️ Round {round_no} • Match {match['match_number']}\n"
                f"{_esc(_name(p1))} vs {_esc(_name(p2))}\n\n"
                "⏳ Preparing cards..."
            ),
            parse_mode="HTML",
        )
        room_id = await db.create_room(
            chat_id=tournament["group_id"],
            room_number=f"T{round_no}-M{match['match_number']}",
            player1_id=match["player1_id"],
            room_message_id=placeholder.message_id,
            tournament_id=tournament_id,
            tournament_round=round_no,
            tournament_match_id=match["id"],
        )
        if not await db.join_room(room_id, match["player2_id"]):
            await db.cancel_room(room_id)
            await db.finish_tournament_match(
                match["id"], match["player1_id"], "opponent_unavailable"
            )
            continue
        if not await db.activate_tournament_match(match["id"], room_id):
            await db.cancel_room(room_id)
            continue
        from game import start_game_countdown
        create_background_task(
            start_game_countdown(
                context, room_id, tournament["group_id"], p1, p2, placeholder.message_id
            ),
            name=f"tournament-countdown-{room_id}",
        )
        available_slots -= 1


async def _announce_bracket(context, tournament_id: str, intro: str = ""):
    tournament = await db.get_tournament(tournament_id)
    if not tournament:
        return
    matches = await db.get_tournament_matches(tournament_id)
    lines = [intro, f"🏆 <b>{_esc(tournament['title'])}</b>", ""]
    for round_no in sorted({m["round"] for m in matches}):
        lines.append(f"<b>Round {round_no}</b>")
        for match in [m for m in matches if m["round"] == round_no]:
            p1 = await db.get_user(match["player1_id"])
            p2 = await db.get_user(match["player2_id"]) if match.get("player2_id") else None
            if match["status"] == "bye":
                result = f"{_esc(_name(p1))} advances by bye"
            elif match.get("winner_id"):
                winner = await db.get_user(match["winner_id"])
                result = f"{_esc(_name(winner))} ✅"
            else:
                result = f"{_esc(_name(p1))} vs {_esc(_name(p2))}"
            lines.append(f"⚔️ M{match['match_number']}: {result}")
        lines.append("")
    try:
        await context.bot.send_message(
            chat_id=tournament["group_id"], text="\n".join(lines), parse_mode="HTML"
        )
    except (BadRequest, Forbidden):
        pass


async def _cleanup_match_messages(context, room: dict):
    for key in ("live_message_id", "last_call_message_id", "group_panel_message_id"):
        message_id = room.get(key)
        if not message_id:
            continue
        try:
            await context.bot.delete_message(
                chat_id=room["chat_id"], message_id=message_id
            )
        except (BadRequest, Forbidden):
            pass


async def handle_tournament_match_finished(
    context: ContextTypes.DEFAULT_TYPE, room: dict, winner_id: int, reason: str = "bingo"
):
    tournament_id = room.get("tournament_id")
    match_id = room.get("tournament_match_id")
    if not tournament_id or not match_id:
        return False
    async with TOURNAMENT_LOCKS[tournament_id]:
        match = (
            await db.get_tournament_match_by_room(room["id"])
            if room.get("id")
            else None
        )
        if not match or match["id"] != match_id:
            match = next(
                (m for m in await db.get_tournament_matches(tournament_id)
                 if m["id"] == match_id), None
            )
        if not match or not await db.finish_tournament_match(match["id"], winner_id, reason):
            return True
        if room.get("id"):
            await db.finish_room(room["id"])
        await _cleanup_match_messages(context, room)
        tournament = await db.get_tournament(tournament_id)
        if not tournament:
            return True

        loser_id = room["player2_id"] if winner_id == room["player1_id"] else room["player1_id"]
        winner = await db.get_user(winner_id)
        loser = await db.get_user(loser_id)
        try:
            await context.bot.send_message(
                chat_id=tournament["group_id"],
                text=(
                    f"🏆 <b>Tournament Match Complete</b>\n"
                    f"Round {match['round']} • Match {match['match_number']}\n"
                    f"✅ {_esc(_name(winner))} advances\n"
                    f"❌ {_esc(_name(loser))} is eliminated\n"
                    f"📌 Result: {_esc(reason)}"
                ),
                parse_mode="HTML",
            )
        except (BadRequest, Forbidden):
            pass

        round_matches = await db.get_tournament_matches(tournament_id, match["round"])
        if any(item["status"] == "pending" for item in round_matches):
            await _launch_pending_round(context, tournament_id, match["round"])
            round_matches = await db.get_tournament_matches(tournament_id, match["round"])
        if any(item["status"] == "active" for item in round_matches):
            return True

        winners = [item["winner_id"] for item in round_matches if item.get("winner_id")]
        if len(winners) == 1:
            if await db.complete_tournament(tournament_id, winners[0]):
                champion = await db.get_user(winners[0])
                prize = int(tournament.get("prize_coins", 0) or 0)
                text = (
                    f"👑 <b>TOURNAMENT CHAMPION</b>\n\n"
                    f"🏆 {_esc(_name(champion))}\n"
                    f"🎁 Prize: <b>+{prize:,} Bingo Coins</b>\n"
                    f"📛 {_esc(tournament.get('title'))}"
                )
                await context.bot.send_message(
                    chat_id=tournament["group_id"], text=text, parse_mode="HTML"
                )
                try:
                    await context.bot.send_message(
                        chat_id=winners[0], text=text, parse_mode="HTML"
                    )
                except (BadRequest, Forbidden):
                    pass
            return True

        next_round = match["round"] + 1
        await _create_round(tournament, next_round, winners)
        await _announce_bracket(
            context, tournament_id, f"✅ Round {match['round']} complete. Round {next_round} is next."
        )
        await _launch_pending_round(context, tournament_id, next_round)
    return True


async def handle_tournament_forfeit(
    context: ContextTypes.DEFAULT_TYPE, room: dict, winner_id: int
):
    """Resolve a tournament forfeit as an advancement, never a dead bracket."""
    return await handle_tournament_match_finished(context, room, winner_id, "forfeit")


async def cmd_tournament_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tournament = await db.get_active_tournament()
    if not tournament:
        await update.message.reply_text("No active tournament.")
        return
    await update.message.reply_text(
        _registration_text(tournament, await db.count_tournament_players(tournament["id"])),
        reply_markup=_active_keyboard(tournament["id"])
        if tournament["status"] == "registration" else None,
        parse_mode="HTML",
    )
    if tournament["status"] == "active":
        await _announce_bracket(context, tournament["id"])


async def cmd_playerlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    tournament = await db.get_active_tournament()
    if not tournament:
        await update.message.reply_text("❌ No active tournament.")
        return
    players = await db.get_tournament_players(tournament["id"])
    lines = [f"🏆 <b>Players ({len(players)}/{tournament['max_players']})</b>"]
    for index, player in enumerate(players, 1):
        username = f"@{player['username']}" if player.get("username") else "no username"
        lines.append(f"{index}. {_esc(player.get('first_name') or 'Player')} — {username}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_cancel_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_ok(update):
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return
    tournament = await db.get_active_tournament()
    if not tournament:
        await update.message.reply_text("❌ No active tournament.")
        return
    result = await db.cancel_tournament(tournament["id"])
    if tournament.get("registration_message_id"):
        try:
            await context.bot.edit_message_text(
                chat_id=tournament["group_id"],
                message_id=tournament["registration_message_id"],
                text=f"❌ <b>{_esc(tournament['title'])}</b> was cancelled.\n"
                     f"💸 Entry fees refunded: <b>{result['refunds']:,} Bingo Coins</b>",
                parse_mode="HTML",
            )
        except (BadRequest, Forbidden):
            pass
    await update.message.reply_text(
        f"✅ Tournament cancelled. Refunded {result['refunds']:,} Bingo Coins."
    )


async def handle_tournament_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tournament_id = query.data.split(":", 1)[1]
    tournament = await db.get_tournament(tournament_id)
    if not tournament:
        await query.answer("Tournament not found.", show_alert=True)
        return
    await query.answer()
    await query.message.reply_text(
        _registration_text(tournament, await db.count_tournament_players(tournament_id)),
        parse_mode="HTML",
    )