import os
import asyncio
import logging
import random
import re
from html import escape
from datetime import timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest, Forbidden
from webserver import start_webserver

import database as db
from rooms import cmd_bingo, handle_join_callback, handle_cancel_room_callback, cmd_stopbingo
from game import (
    handle_card_callback,
    handle_rematch_callback,
    handle_cancel_game_callback,
    handle_forfeit_ask_callback,
    handle_forfeit_confirm_callback,
    _try_unpin,
    _log,
)
from economy import award_winner, record_loss, process_forfeit
from leaderboard import build_leaderboard_text, build_leaderboard_keyboard
from tournament import (
    cmd_tournament,
    cmd_tournament_add,
    cmd_tournament_message,
    cmd_tournament_disqualify,
    cmd_tournament_start,
    cmd_tournament_status,
    cmd_announce_tournament,
    cmd_playerlist,
    cmd_cancel_tournament,
    handle_tournament_join,
    handle_tournament_leave,
    handle_tournament_status_callback,
    handle_tournament_forfeit,
)
from utils import display_name_from_db, display_name
from models import (
    LINES_TO_WIN,
    WIN_COINS,
    FORFEIT_COST,
    CANCEL_FREE_THRESHOLD,
    OWNER_IDS,
    LOGGER_GROUP_ID,
    SUPPORT_CHANNEL,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _send_help_message(update: Update, context: ContextTypes.DEFAULT_TYPE, *, via_callback=False):
    user = update.effective_user
    name = user.first_name or user.username or "Player"
    text = f"""🎮 𝗪𝗲𝗹𝗰𝗼𝗺𝗲, ─ {name}

🎯 𝗦𝘁𝗮𝗿𝘁 𝗮 𝗚𝗮𝗺𝗲

🎮 Create or join a 1v1 match with another player.
🤝 Once both players join, the game begins.
🔢 Each player gets a 5×5 Bingo card with numbers 1–25.

📩 Start the bot in private using /start to receive your card and game updates.

🔄 𝗛𝗼𝘄 𝘁𝗵𝗲 𝗚𝗮𝗺𝗲 𝗪𝗼𝗿𝗸𝘀
👆 Players take turns choosing numbers.
✅ The selected number is marked on both Bingo cards.
🧠 Complete your lines before your opponent!

🏆 𝗛𝗼𝘄 𝘁𝗼 𝗪𝗶𝗻
Complete 5 full lines to make BINGO:
➖ Rows — Left to right
⬇️ Columns — Top to bottom
✖️ Diagonals — Across the card

🎉 The first player to complete 5 lines wins the match! 👑🏆

💎 𝗖𝗼𝗶𝗻 𝗩𝗮𝘂𝗹𝘁
Use /balance or /wallet for the interactive wallet.
Use /deposit and /withdraw to protect your coins.
Use /daily for a UTC daily reward with a streak bonus.
Use /transactions or /history to review recent coin activity.
Use /bet or bbet for a 50/50 bet, and /steal or ssteal for the daily steal mode.

🥇 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱
Compete with other players and fight for the #1 spot! 👑

❌ 𝗖𝗮𝗻𝗰𝗲𝗹𝗹𝗶𝗻𝗴 & 𝗙𝗮𝗶𝗿 𝗣𝗹𝗮𝘆
Use /cancel if you cannot continue the current match. 🤝
⚠️ Play fairly and don't keep your opponent waiting!

✨ 𝗤𝘂𝗶𝗰𝗸 𝗦𝘁𝗮𝗿𝘁
1️⃣ Start the Bot → 2️⃣ Join a Match → 3️⃣ Play → 4️⃣ Complete BINGO → 5️⃣ WIN! 🏆"""
    buttons = [[InlineKeyboardButton("📢 Support Channel", url=SUPPORT_CHANNEL)]] if SUPPORT_CHANNEL.startswith(("http://", "https://")) else []
    markup = InlineKeyboardMarkup(buttons)
    if via_callback:
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username, user.first_name)

    name = user.first_name or user.username or "Player"
    text = f"""🎮 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 ─͢ {name} 🎉
🎯 𝗛𝗼𝘄 𝘁𝗼 𝗣𝗹𝗮𝘆?
● Start a 1v1 game and challenge another player.
● Both players get a 5x5 Bingo card with numbers 1-25.
● Take turns choosing numbers.
● The chosen number is marked on both cards.
● Complete 5 lines — Rows, Columns or Diagonals — to complete BINGO. The first player to complete it wins 🎊

💰 𝗣𝗹𝗮𝘆 & 𝗘𝗮𝗿𝗻
● 𝗪𝗶𝗻 𝗺𝗮𝘁𝗰𝗵𝗲𝘀 𝗮𝗻𝗱 𝗲𝗮𝗿𝗻 𝗕𝗶𝗻𝗴𝗼 𝗖𝗼𝗶𝗻𝘀
● 𝗖𝗵𝗲𝗰𝗸 𝘆𝗼𝘂𝗿 𝗦𝘁𝗮𝘁𝘀 & 𝗪𝗶𝗻𝘀
● 𝗖𝗹𝗶𝗺𝗯 𝘁𝗵𝗲 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱
● 𝗝𝗼𝗶𝗻 𝗧𝗼𝘂𝗿𝗻𝗮𝗺𝗲𝗻𝘁𝘀 & 𝗰𝗼𝗺𝗽𝗲𝘁𝗲 𝗳𝗼𝗿 𝗿𝗲𝘄𝗮𝗿𝗱𝘀!

✨ 𝗡𝗼 𝗰𝗼𝗺𝗽𝗹𝗶𝗰𝗮𝘁𝗲𝗱 𝗿𝘂𝗹𝗲𝘀 — 𝗷𝘂𝘀𝘁 𝗽𝗹𝗮𝘆, 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝘆𝗼𝘂𝗿 𝗕𝗜𝗡𝗚𝗢 & 𝗵𝗮𝘃𝗲 𝗳𝘂𝗻! ❤️

👇 Start playing with your friends. 🎮
/bingo = to start the match.
/leaderboard = rankings of the top ten users
/profile = for your stats
/balance = wallet + bank balance
/daily = claim your daily reward
/transactions = recent coin history
/deposit = put coins in bank
/withdraw = take coins from bank
/bet or bbet = bet Bingo Coins
/steal or ssteal = try to steal coins
/tournament_status = view the current tournament

👑 𝗣𝗹𝗮𝘆 • 𝗪𝗶𝗻 • 𝗕𝗲𝗰𝗼𝗺𝗲 𝘁𝗵𝗲 𝗕𝗶𝗻𝗴𝗼 𝗖𝗵𝗮𝗺𝗽𝗶𝗼𝗻! 🏆"""
    bot_username = context.bot.username
    add_me_url = f"https://t.me/{bot_username}?startgroup=true" if bot_username else None
    first_row = []
    if SUPPORT_CHANNEL.startswith(("http://", "https://")):
        first_row.append(InlineKeyboardButton("📢 Support Channel", url=SUPPORT_CHANNEL))
    if add_me_url:
        first_row.append(InlineKeyboardButton("➕ Add Me", url=add_me_url))
    keyboard_rows = []
    if first_row:
        keyboard_rows.append(first_row)
    keyboard_rows.append([InlineKeyboardButton("ℹ️ Detail Help", callback_data="detail_help")])
    keyboard = InlineKeyboardMarkup(keyboard_rows)
    await update.message.reply_text(text, reply_markup=keyboard)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_help_message(update, context)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    player = await db.get_user(user.id)
    if not player:
        await update.message.reply_text(
            "❌ You're not registered yet! Send /start first."
        )
        return

    name = display_name_from_db(player)
    games = player["games_played"]
    wins = player["wins"]
    losses = player["losses"]
    win_rate = (wins / games * 100) if games > 0 else 0.0
    streak = player["current_streak"]
    longest = player["longest_streak"]
    coins = int(player.get("coins", 0) or 0)
    bank = int(player.get("bank", 0) or 0)
    total_coins = coins + bank

    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Profile — {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👛 Wallet: <b>{coins:,}</b>\n"
        f"🏦 Bank: <b>{bank:,}</b>\n"
        f"💎 Total Wealth: <b>{total_coins:,}</b>\n"
        f"🎮 Games Played: <b>{games}</b>\n"
        f"🏆 Wins: <b>{wins}</b>\n"
        f"😔 Losses: <b>{losses}</b>\n"
        f"📈 Win Rate: <b>{win_rate:.1f}%</b>\n"
        f"🔥 Current Streak: <b>{streak}</b>\n"
        f"⭐ Longest Streak: <b>{longest}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
    )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    is_group = chat.type in ("group", "supergroup")
    chat_id = chat.id if is_group else 0
    scope = "chat" if is_group else "global"
    time_filter = "all_time"

    chat_title = chat.title if is_group else ""
    text = await build_leaderboard_text(scope, time_filter, chat_id, chat_title)
    keyboard = build_leaderboard_keyboard(scope, time_filter, chat_id)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def handle_leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "lb_nochat":
        await query.answer(
            "Current Chat leaderboard is only available in group chats!", show_alert=True
        )
        return

    parts = data.split(":")
    if len(parts) < 4:
        await query.answer()
        return

    scope = parts[1]
    time_filter = parts[2]
    chat_id = int(parts[3])

    chat_title = ""
    if scope == "chat" and chat_id:
        try:
            chat_info = await context.bot.get_chat(chat_id)
            chat_title = chat_info.title or ""
        except Exception:
            pass

    text = await build_leaderboard_text(scope, time_filter, chat_id, chat_title)
    keyboard = build_leaderboard_keyboard(scope, time_filter, chat_id)

    try:
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except BadRequest:
        pass
    await query.answer()


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cancel command — respects the new cancellation rules:
    • Waiting room   → always free, no coins involved.
    • Playing, ≤ CANCEL_FREE_THRESHOLD numbers called
                     → free cancel, no winner, no coins.
    • Playing, > CANCEL_FREE_THRESHOLD numbers called
                     → forfeit: FORFEIT_COST deducted from the caller,
                        opponent receives nothing, match is not counted.
    """
    user = update.effective_user

    player = await db.get_user(user.id)
    if not player:
        await update.message.reply_text("❌ You're not registered. Send /start first.")
        return

    room = await db.get_player_active_room(user.id)
    if not room:
        await update.message.reply_text("❌ You are not in any active game right now.")
        return

    forfeiter_name = display_name_from_db(player)

    # ── Waiting room (no game started yet) ────────────────────────────────
    if room["status"] == "waiting":
        await db.cancel_room(room["id"])
        try:
            await context.bot.edit_message_text(
                chat_id=room["chat_id"],
                message_id=room["room_message_id"],
                text=f"❌ <b>Room #{room['room_number']}</b> was cancelled by {forfeiter_name}.",
                parse_mode="HTML",
            )
        except (BadRequest, KeyError):
            pass
        await update.message.reply_text(
            f"✅ Your waiting room <b>#{room['room_number']}</b> has been cancelled.",
            parse_mode="HTML",
        )
        return

    # ── Game in progress ──────────────────────────────────────────────────
    called = room.get("called_numbers") or []
    chat_id = room["chat_id"]
    opponent_id = (
        room["player2_id"] if user.id == room["player1_id"] else room["player1_id"]
    )
    opponent = await db.get_user(opponent_id)
    opponent_name = display_name_from_db(opponent) if opponent else "Opponent"

    # Tournament matches cannot be silently cancelled: doing so would leave
    # the knockout bracket waiting forever. A /cancel is recorded as a loss.
    if room.get("tournament_id"):
        await handle_tournament_forfeit(context, room, opponent_id)
        await update.message.reply_text(
            f"🏳️ You forfeited tournament match #{room['room_number']}.\n"
            f"✅ {opponent_name} advances to the next round."
        )
        return

    if len(called) <= CANCEL_FREE_THRESHOLD:
        # ── Free cancel (1–5 numbers called) ──────────────────────────────
        await db.cancel_room(room["id"])
        for mid_key in ("live_message_id", "last_call_message_id", "group_panel_message_id"):
            mid = room.get(mid_key)
            if mid:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass

        cancel_text = (
            f"🚫 <b>Match Cancelled — Room #{room['room_number']}</b>\n\n"
            f"<b>{forfeiter_name}</b> cancelled the game.\n"
            f"• No winner declared\n"
            f"• No coins awarded\n"
            f"• Match does not count toward any leaderboard or event"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=cancel_text, parse_mode="HTML")
        except Exception:
            pass
     
    else:
        # ── Paid forfeit (6+ numbers called) ──────────────────────────────
        # Check balance first (non-deducting read — the atomic deduct happens in process_forfeit)
        if player.get("coins", 0) < FORFEIT_COST:
            await update.message.reply_text(
                f"❌ You need at least <b>{FORFEIT_COST} coins</b> to forfeit this match.\n"
                f"Your balance: <b>{player.get('coins', 0)} coins</b>",
                parse_mode="HTML",
            )
            return
        success = await process_forfeit(user.id, chat_id)
        if not success:
            # Race: balance dropped between the check and the atomic deduct
            await update.message.reply_text(
                f"❌ You need at least <b>{FORFEIT_COST} coins</b> to forfeit this match.",
                parse_mode="HTML",
            )
            return
        await db.cancel_room(room["id"])
        for mid_key in ("live_message_id", "last_call_message_id", "group_panel_message_id"):
            mid = room.get(mid_key)
            if mid:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        forfeit_text = (
            f"🏳️ <b>Forfeit — Room #{room['room_number']}</b>\n\n"
            f"😔 <b>{forfeiter_name}</b> forfeited the match.\n"
            f"💸 <b>−{FORFEIT_COST} coins</b> deducted from {forfeiter_name}'s balance.\n"
            f"🤝 No coins awarded to either player.\n"
            f"📊 This match does not count toward event progress or leaderboards."
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=forfeit_text, parse_mode="HTML")
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=opponent_id,
                text=(
                    f"🏳️ <b>{forfeiter_name}</b> forfeited Room #{room['room_number']}.\n"
                    f"You were not awarded any coins (match ended by forfeit)."
                ),
                parse_mode="HTML",
            )
        except (Forbidden, BadRequest):
            pass
        await update.message.reply_text(
            f"🏳️ You forfeited Room <b>#{room['room_number']}</b>.\n"
            f"💸 <b>−{FORFEIT_COST} coins</b> deducted from your balance.",
            parse_mode="HTML",
        )

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id not in OWNER_IDS:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    source = update.message.reply_to_message
    if not source and not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "• Reply to a message with /broadcast to send it to all players and groups\n"
            "• /broadcast <text> to send a plain message to all players and groups"
        )
        return

    user_ids = await db.get_all_user_ids()
    group_ids = await db.get_all_group_chat_ids()

    status_msg = await update.message.reply_text(
        f"📡 Broadcasting to <b>{len(user_ids)}</b> players and <b>{len(group_ids)}</b> Telegram groups...",
        parse_mode="HTML",
    )

    sent_users = failed_users = sent_groups = failed_groups = 0

    for uid in user_ids:
        try:
            if source:
                await source.copy(chat_id=uid)
            else:
                await context.bot.send_message(
                    chat_id=uid, text=" ".join(context.args), parse_mode="HTML"
                )
            sent_users += 1
        except (Forbidden, BadRequest):
            failed_users += 1
        except Exception:
            failed_users += 1
        await asyncio.sleep(0.05)

    for gid in group_ids:
        try:
            if source:
                await source.copy(chat_id=gid)
            else:
                await context.bot.send_message(
                    chat_id=gid, text=" ".join(context.args), parse_mode="HTML"
                )
            sent_groups += 1
        except (Forbidden, BadRequest):
            failed_groups += 1
        except Exception:
            failed_groups += 1
        await asyncio.sleep(0.05)

    try:
        await status_msg.edit_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Broadcast Complete!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Player DMs</b>\n📨 Sent: <b>{sent_users}</b>\n❌ Failed: <b>{failed_users}</b>\n\n"
            f"👥 <b>Telegram Groups</b>\n📨 Sent: <b>{sent_groups}</b>\n❌ Failed: <b>{failed_groups}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
        )
    except BadRequest:
        pass


async def _ensure_user(update: Update):
    user = update.effective_user
    player = await db.get_user(user.id)
    if not player:
        await db.create_user(user.id, user.username, user.first_name)
        player = await db.get_user(user.id)
    return player


def _coin_bar(value: int, total: int, width: int = 12) -> str:
    """Render a compact wallet/bank split for Telegram's text UI."""
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, round((value / total) * width)))
    return "▰" * filled + "▱" * (width - filled)


def _economy_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Quick actions for the player's private coin dashboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏦 Deposit 25%", callback_data=f"eco:deposit:25:{user_id}"),
            InlineKeyboardButton("🏦 Deposit All", callback_data=f"eco:deposit:all:{user_id}"),
        ],
        [
            InlineKeyboardButton("💸 Withdraw 25%", callback_data=f"eco:withdraw:25:{user_id}"),
            InlineKeyboardButton("💸 Withdraw All", callback_data=f"eco:withdraw:all:{user_id}"),
        ],
        [
            InlineKeyboardButton("🎲 Quick Bet 25%", callback_data=f"eco:bet:25:{user_id}"),
            InlineKeyboardButton("🎲 Quick Bet 50%", callback_data=f"eco:bet:50:{user_id}"),
        ],
        [
            InlineKeyboardButton("🕵️ Steal Guide", callback_data=f"eco:steal_help:0:{user_id}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"eco:refresh:0:{user_id}"),
        ],
        [
            InlineKeyboardButton("🎁 Daily Reward", callback_data=f"eco:daily:0:{user_id}"),
            InlineKeyboardButton("🧾 History", callback_data=f"eco:history:0:{user_id}"),
        ],
    ])


def _economy_text(player: dict) -> str:
    wallet = int(player.get("coins", 0) or 0)
    bank = int(player.get("bank", 0) or 0)
    total = wallet + bank
    games = int(player.get("games_played", 0) or 0)
    wins = int(player.get("wins", 0) or 0)
    daily_streak = int(player.get("daily_streak", 0) or 0)
    win_rate = (wins / games * 100) if games else 0
    name = escape(display_name_from_db(player))

    return (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "│  💎 <b>BINGO VAULT</b>  │\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👤 <b>{name}</b>\n\n"
        f"👛 <b>Wallet</b>  <code>{wallet:,}</code>\n"
        f"🏦 <b>Bank</b>    <code>{bank:,}</code>\n"
        f"💰 <b>Total wealth</b>  <code>{total:,}</code>\n"
        f"   <code>{_coin_bar(wallet, total)}</code>  ▰ wallet  ▱ bank\n\n"
        f"🎮 {games} games  •  🏆 {wins} wins  •  📈 {win_rate:.1f}% win rate\n"
        f"🔥 Daily streak: <b>{daily_streak}</b>\n\n"
        "💡 Wallet coins are ready for games, bets and steals.\n"
        "   Bank coins stay protected until you withdraw them."
    )


def _amount_from_share(raw: str, balance: int):
    if raw == "all":
        return balance
    try:
        share = int(raw)
    except ValueError:
        return None
    if share not in (25, 50, 75):
        return None
    return balance * share // 100


async def _settle_bet(user_id: int, amount: int):
    """Reserve and resolve one bet, returning None if the reserve failed."""
    if not await db.place_bet(user_id, amount):
        return None
    won = random.choice((True, False))
    if won:
        await db.resolve_bet(user_id, amount * 2)
    return won


async def _show_economy_panel(query, player: dict):
    try:
        await query.edit_message_text(
            _economy_text(player),
            parse_mode="HTML",
            reply_markup=_economy_keyboard(player["telegram_id"]),
        )
    except BadRequest:
        # Telegram returns this when Refresh is pressed without changes.
        pass


def _history_event_label(event: str) -> str:
    return {
        "daily_reward": "🎁 Daily reward",
        "deposit": "🏦 Deposit",
        "withdraw": "💸 Withdraw",
        "bet_stake": "🎲 Bet stake",
        "bet_payout": "🎉 Bet payout",
        "game_win": "🏆 Bingo win",
        "forfeit_fee": "🏳️ Forfeit fee",
        "steal_received": "🕵️ Steal received",
        "stolen_from": "🛡️ Stolen from you",
        "transfer_sent": "🎁 Transfer sent",
        "transfer_received": "🎁 Transfer received",
        "coin_grant": "💎 Coin grant",
    }.get(event, event.replace("_", " ").title())


def _economy_history_text(player: dict, history: list[dict]) -> str:
    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━╮",
        "│  🧾 <b>COIN HISTORY</b>  │",
        "╰━━━━━━━━━━━━━━━━━━━━╯",
        "",
        f"👤 <b>{escape(display_name_from_db(player))}</b>",
        "",
    ]
    if not history:
        lines.append("📭 No economy activity recorded yet.")
        return "\n".join(lines)

    for entry in history:
        amount = int(entry.get("amount", 0) or 0)
        sign = "+" if amount > 0 else ""
        created = entry.get("created_at")
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        stamp = created.strftime("%d %b, %H:%M") if created else "recently"
        lines.append(
            f"{_history_event_label(entry.get('event', 'activity'))} "
            f"<b>{sign}{amount:,}</b>  <i>{stamp} UTC</i>"
        )
    lines.extend(["", "Use /balance to return to your vault."])
    return "\n".join(lines)


async def _show_economy_history(query, player: dict):
    history = await db.get_economy_history(player["telegram_id"])
    await query.edit_message_text(
        _economy_history_text(player, history),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⬅️ Back to Vault",
                callback_data=f"eco:refresh:0:{player['telegram_id']}",
            )
        ]]),
    )


def _parse_amount_arg(raw: str):
    raw = raw.strip().lower().replace(",", "")
    if raw == "all":
        return "all"
    try:
        value = int(raw)
        return value
    except ValueError:
        return None


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    await update.message.reply_text(
        _economy_text(user),
        parse_mode="HTML",
        reply_markup=_economy_keyboard(user["telegram_id"]),
    )


async def cmd_economy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for the interactive wallet dashboard."""
    await cmd_balance(update, context)


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    reward = await db.claim_daily_reward(user["telegram_id"])
    if not reward:
        await update.message.reply_text("❌ Your wallet could not be found. Send /start first.")
        return
    if not reward["claimed"]:
        await update.message.reply_text(
            "⏳ <b>Daily reward already claimed</b>\n\n"
            f"🔥 Current streak: <b>{reward['streak']} day(s)</b>\n"
            "Come back after 00:00 UTC for the next reward.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    fresh = await db.get_user(user["telegram_id"])
    await update.message.reply_text(
        "🎁 <b>DAILY REWARD CLAIMED</b>\n\n"
        f"💰 Reward: <b>+{reward['reward']:,}</b> coins\n"
        f"🔥 Streak: <b>{reward['streak']} day(s)</b>\n"
        f"👛 Wallet: <b>{int(fresh.get('coins', 0)):,}</b>\n\n"
        "Keep your streak alive to unlock bigger rewards.",
        parse_mode="HTML",
        reply_markup=_economy_keyboard(user["telegram_id"]),
    )


async def cmd_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    history = await db.get_economy_history(user["telegram_id"])
    await update.message.reply_text(
        _economy_history_text(user, history),
        parse_mode="HTML",
        reply_markup=_economy_keyboard(user["telegram_id"]),
    )


async def handle_economy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 4:
        await query.answer("This wallet action has expired.", show_alert=True)
        return

    action, raw_amount, owner_id = parts[1], parts[2], parts[3]
    try:
        owner_id = int(owner_id)
    except ValueError:
        await query.answer("Invalid wallet action.", show_alert=True)
        return
    if query.from_user.id != owner_id:
        await query.answer("This wallet panel belongs to another player.", show_alert=True)
        return

    player = await db.get_user(owner_id)
    if not player:
        await query.answer("Send /start first to create your wallet.", show_alert=True)
        return

    if action == "daily":
        reward = await db.claim_daily_reward(owner_id)
        if not reward or not reward["claimed"]:
            streak = reward["streak"] if reward else 0
            await query.answer("Daily reward already claimed today.", show_alert=True)
            await query.edit_message_text(
                _economy_text(player)
                + f"\n\n⏳ Daily reward claimed • 🔥 {streak}-day streak",
                parse_mode="HTML",
                reply_markup=_economy_keyboard(owner_id),
            )
            return
        fresh = await db.get_user(owner_id)
        await query.answer(f"+{reward['reward']:,} coins claimed! 🎁")
        await query.edit_message_text(
            _economy_text(fresh)
            + f"\n\n🎁 <b>Daily reward:</b> +{reward['reward']:,} coins"
            + f"\n🔥 <b>Streak:</b> {reward['streak']} day(s)",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(owner_id),
        )
        return

    if action == "history":
        await query.answer()
        await _show_economy_history(query, player)
        return

    if action == "refresh":
        await _show_economy_panel(query, player)
        await query.answer("Wallet refreshed.")
        return

    if action == "steal_help":
        await query.answer()
        await query.edit_message_text(
            "🕵️ <b>STEAL MODE</b>\n\n"
            "Reply to a player's message with <code>/steal</code>, or use "
            "<code>/steal @username</code>.\n\n"
            "• 10 attempts per UTC day\n"
            "• Only wallet coins can be stolen\n"
            "• The target must have at least 1,000 wallet coins\n"
            "• A 10% operation fee is removed from the stolen amount\n\n"
            "Use it strategically — the bank is protected.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(owner_id),
        )
        return

    if action == "bet":
        wallet = int(player.get("coins", 0) or 0)
        amount = _amount_from_share(raw_amount, wallet)
        if not amount:
            await query.answer("Your wallet is too small for that bet.", show_alert=True)
            return
        won = await _settle_bet(owner_id, amount)
        if won is None:
            await query.answer("Bet could not be placed. Refresh your wallet.", show_alert=True)
            return
        fresh = await db.get_user(owner_id)
        result = (
            f"🎉 <b>BET WON</b>\n\n🎲 Stake: <b>{amount:,}</b>\n"
            f"💎 Profit: <b>+{amount:,}</b>\n\n"
            f"👛 New wallet: <b>{int(fresh.get('coins', 0)):,}</b>"
            if won else
            f"💥 <b>BET LOST</b>\n\n🎲 Stake lost: <b>{amount:,}</b>\n\n"
            f"👛 New wallet: <b>{int(fresh.get('coins', 0)):,}</b>"
        )
        await query.answer("Bet won! 🎉" if won else "Better luck next time.")
        await query.edit_message_text(
            result + "\n\n" + _economy_text(fresh),
            parse_mode="HTML",
            reply_markup=_economy_keyboard(owner_id),
        )
        return

    if action not in ("deposit", "withdraw"):
        await query.answer("Unknown wallet action.", show_alert=True)
        return

    balance_key = "coins" if action == "deposit" else "bank"
    available = int(player.get(balance_key, 0) or 0)
    amount = _amount_from_share(raw_amount, available)
    if not amount:
        await query.answer("There are not enough coins for that action.", show_alert=True)
        return

    success = (
        await db.deposit_coins(owner_id, amount)
        if action == "deposit"
        else await db.withdraw_coins(owner_id, amount)
    )
    if not success:
        await query.answer("Your balance changed. Refresh and try again.", show_alert=True)
        return

    fresh = await db.get_user(owner_id)
    label = "Deposited into the bank" if action == "deposit" else "Moved to your wallet"
    await query.answer(f"{label}: {amount:,} coins.")
    await _show_economy_panel(query, fresh)


async def cmd_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    if not context.args:
        await update.message.reply_text(
            "🏦 <b>Deposit to your protected bank</b>\n\n"
            "Use <code>/deposit 50000</code> or <code>/deposit all</code>.\n"
            "Your bank balance cannot be used for bets or steals.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    amount = context.args[0]
    wallet = int(user.get("coins", 0) or 0)
    if amount.lower() == "all":
        amount = wallet
    else:
        amount = _parse_amount_arg(amount)
    if not isinstance(amount, int) or amount <= 0:
        await update.message.reply_text(
            "❌ Enter a valid positive amount, or use <code>all</code>.",
            parse_mode="HTML",
        )
        return
    if not await db.deposit_coins(update.effective_user.id, amount):
        await update.message.reply_text(
            f"❌ <b>Deposit not completed</b>\n\n"
            f"👛 Available wallet: <b>{wallet:,}</b>\n"
            f"💸 Requested: <b>{amount:,}</b>",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    fresh = await db.get_user(update.effective_user.id)
    await update.message.reply_text(
        f"✅ <b>Deposit complete</b>\n\n"
        f"🏦 Protected: <b>+{amount:,}</b>\n"
        f"🏦 Bank balance: <b>{int(fresh.get('bank', 0)):,}</b>\n"
        f"💎 Total wealth: <b>{int(fresh.get('bank', 0)) + int(fresh.get('coins', 0)):,}</b>",
        parse_mode="HTML",
        reply_markup=_economy_keyboard(user["telegram_id"]),
    )


async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    if not context.args:
        await update.message.reply_text(
            "💸 <b>Withdraw from your protected bank</b>\n\n"
            "Use <code>/withdraw 50000</code> or <code>/withdraw all</code>.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    amount = context.args[0]
    bank = int(user.get("bank", 0) or 0)
    if amount.lower() == "all":
        amount = bank
    else:
        amount = _parse_amount_arg(amount)
    if not isinstance(amount, int) or amount <= 0:
        await update.message.reply_text(
            "❌ Enter a valid positive amount, or use <code>all</code>.",
            parse_mode="HTML",
        )
        return
    if not await db.withdraw_coins(update.effective_user.id, amount):
        await update.message.reply_text(
            f"❌ <b>Withdrawal not completed</b>\n\n"
            f"🏦 Available bank: <b>{bank:,}</b>\n"
            f"💸 Requested: <b>{amount:,}</b>",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    fresh = await db.get_user(update.effective_user.id)
    await update.message.reply_text(
        f"✅ <b>Withdrawal complete</b>\n\n"
        f"👛 Wallet received: <b>+{amount:,}</b>\n"
        f"👛 Wallet balance: <b>{int(fresh.get('coins', 0)):,}</b>\n"
        f"💎 Total wealth: <b>{int(fresh.get('bank', 0)) + int(fresh.get('coins', 0)):,}</b>",
        parse_mode="HTML",
        reply_markup=_economy_keyboard(user["telegram_id"]),
    )


async def cmd_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    args = list(context.args)
    # MessageHandler does not populate context.args for plain-text aliases.
    if not args and update.message and update.message.text:
        parts = update.message.text.strip().split()
        if parts and parts[0].lower() in ("bbet", "bet"):
            args = parts[1:]
    if not args:
        await update.message.reply_text(
            "🎰 <b>BINGO BETS</b>\n\n"
            "Use <code>/bet 100000</code>, <code>bbet 100000</code> or <code>bbet all</code>.\n\n"
            "🏦 Banked coins are protected and cannot be bet directly.\n"
            "🎲 Win = your stake returned + equal profit.\n"
            "💥 Loss = your stake is lost.\n\n"
            f"👛 Current wallet: <b>{int(user.get('coins', 0) or 0):,}</b>",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    raw = args[0]
    wallet = int(user.get("coins", 0) or 0)
    amount = wallet if raw.lower() == "all" else _parse_amount_arg(raw)
    if not isinstance(amount, int) or amount <= 0:
        await update.message.reply_text(
            "❌ Bet amount must be a positive number or <code>all</code>.",
            parse_mode="HTML",
        )
        return
    if amount > wallet:
        await update.message.reply_text(
            f"❌ <b>Not enough wallet coins</b>\n\n"
            f"👛 Wallet: <b>{wallet:,}</b>\n"
            f"🎲 Requested bet: <b>{amount:,}</b>\n\n"
            "Tip: use /deposit to protect coins in your bank.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    won = await _settle_bet(update.effective_user.id, amount)
    if won is None:
        await update.message.reply_text(
            "❌ Bet could not be placed. Your balance may have changed — try again.",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
        return
    fresh = await db.get_user(update.effective_user.id)
    new_wallet = int(fresh.get("coins", 0) or 0)
    if won:
        await update.message.reply_text(
            f"🎉 <b>BET WON</b>\n\n"
            f"🎲 Stake: <b>{amount:,}</b>\n"
            f"💎 Profit: <b>+{amount:,}</b>\n"
            f"💰 Returned: <b>{amount * 2:,}</b>\n\n"
            f"👛 New wallet: <b>{new_wallet:,}</b>",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )
    else:
        await update.message.reply_text(
            f"💥 <b>BET LOST</b>\n\n"
            f"🎲 Stake lost: <b>{amount:,}</b>\n\n"
            f"👛 New wallet: <b>{new_wallet:,}</b>",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(user["telegram_id"]),
        )


async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE, args=None):
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_tg = msg.reply_to_message.from_user
        target = await db.get_user(target_tg.id)
        if target:
            return target
        await db.create_user(target_tg.id, target_tg.username, target_tg.first_name)
        return await db.get_user(target_tg.id)
    args = context.args if args is None else args
    if args:
        raw = args[0].strip()
        if raw.startswith("@"):
            return await db.find_user_by_username(raw[1:])
        if raw.isdigit():
            return await db.get_user(int(raw))
    return None


async def cmd_steal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thief = await _ensure_user(update)
    args = list(context.args)
    if not args and update.message and update.message.text:
        parts = update.message.text.strip().split()
        if parts and parts[0].lower() in ("ssteal", "steal"):
            args = parts[1:]
    target = await _resolve_target(update, context, args)
    if not target:
        await update.message.reply_text(
            "🕵️ <b>STEAL MODE</b>\n\n"
            "Reply to a player's message with <code>/steal</code>, or use "
            "<code>/steal @username</code>.\n\n"
            "The target must have used the bot at least once.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(thief["telegram_id"]),
        )
        return
    thief_id = update.effective_user.id
    target_id = target["telegram_id"]
    if thief_id == target_id:
        await update.message.reply_text(
            "❌ You can't steal from yourself!",
            reply_markup=_economy_keyboard(thief["telegram_id"]),
        )
        return
    allowed, used = await db.consume_steal_attempt(thief_id)
    if not allowed:
        await update.message.reply_text(
            "🚫 <b>Daily steal limit reached</b>\n\n"
            "You have used all <b>10/10</b> attempts for today.\n"
            "Your limit resets at 00:00 UTC.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(thief["telegram_id"]),
        )
        return
    target_coins = int(target.get("coins", 0) or 0)
    if target_coins < 1000:
        await update.message.reply_text(
            f"🛡️ <b>Steal failed</b>\n\n"
            "The target needs at least <b>1,000</b> wallet coins.\n\n"
            f"🎯 Target wallet: <b>{target_coins:,}</b>\n"
            f"📊 Attempts used: <b>{used}/10</b> today",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(thief["telegram_id"]),
        )
        return
    # Random amount is chosen by the bot from the target's wallet balance.
    # Roughly 25%-50%, capped at 100,000; small balances stay proportional.
    upper = min(100000, max(1000, target_coins // 2))
    lower = min(upper, max(1000, target_coins // 4))
    amount = random.randint(lower, upper)
    received = amount * 90 // 100
    if received <= 0:
        await update.message.reply_text(
            "🛡️ Steal failed — the amount was too small.",
            reply_markup=_economy_keyboard(thief["telegram_id"]),
        )
        return
    success = await db.perform_steal(thief_id, target_id, amount, received)
    target_name = display_name_from_db(target)
    if not success:
        await update.message.reply_text(
            "🛡️ <b>Steal failed</b>\n\n"
            "The target's balance changed before the action completed. "
            "Your attempt was still counted.",
            parse_mode="HTML",
            reply_markup=_economy_keyboard(thief["telegram_id"]),
        )
        return
    thief_name = display_name_from_db(thief)
    await update.message.reply_text(
        f"🕵️ <b>STEAL SUCCESSFUL!</b>\n\n"
        f"👤 Thief: <b>{thief_name}</b>\n"
        f"🎯 Target: <b>{target_name}</b>\n"
        f"💰 Stolen: <b>{amount:,}</b>\n"
        f"💸 10% deduction: <b>{amount - received:,}</b>\n"
        f"💎 You received: <b>{received:,}</b>\n\n"
        f"📊 Steal attempts: <b>{used}/10</b> today",
        parse_mode="HTML",
        reply_markup=_economy_keyboard(thief["telegram_id"]),
    )


async def cmd_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check if user is registered
    sender = await db.get_user(user.id)
    if not sender:
        await update.message.reply_text("❌ You're not registered yet! Send /start first.")
        return
    
    # Parse arguments: /give @username amount or /give user_id amount
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/give @username <amount>\n"
            "/give <user_id> <amount>\n\n"
            f"Your coins: 💰 <b>{sender['coins']:,}</b>",
            parse_mode="HTML",
        )
        return
    
    recipient_input = context.args[0]
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number!")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Amount must be greater than 0!")
        return
    
    # Owners are minting authorities: owner /give never deducts the
    # owner's wallet. Normal members can only give from their own balance.
    is_owner = user.id in OWNER_IDS
    if not is_owner and sender["coins"] < amount:
        await update.message.reply_text(
            f"❌ You don't have enough coins!\n"
            f"You have: 💰 <b>{sender['coins']:,}</b>\n"
            f"Trying to give: 💰 <b>{amount:,}</b>",
            parse_mode="HTML",
        )
        return
    
    # Try to find recipient
    recipient = None
    
    # If input looks like a user ID (digits)
    if recipient_input.isdigit():
        recipient_id = int(recipient_input)
        recipient = await db.get_user(recipient_id)
    # If input is a username
    elif recipient_input.startswith("@"):
        username = recipient_input[1:]
        # Search for user with this username
        # We need to add this to the database
        cursor = await db.find_user_by_username(username)
        if cursor:
            recipient = cursor
    
    if not recipient:
        await update.message.reply_text("❌ Recipient not found! Use @username or user_id")
        return
    
    if recipient["telegram_id"] == user.id:
        await update.message.reply_text("❌ You can't give coins to yourself!")
        return
    
    # Transfer coins
    if is_owner:
        success = await db.add_coins(
            recipient["telegram_id"],
            amount
        )
    else:
        success = await db.transfer_coins(
            user.id,
            recipient["telegram_id"],
            amount
        )
    
    if not success:
        await update.message.reply_text("❌ Transfer failed!")
        return
    
    recipient_name = display_name_from_db(recipient)
    
    if is_owner:
        result_text = (
            f"👑 <b>Owner Gift Successful!</b>\n\n"
            f"Created: 💰 <b>{amount:,}</b> coins\n"
            f"To: <b>{recipient_name}</b>\n\n"
            f"💎 Your owner balance was <b>not deducted</b>."
        )
    else:
        result_text = (
            f"✅ <b>Transfer successful!</b>\n\n"
            f"Sent: 💰 <b>{amount:,}</b> coins\n"
            f"To: <b>{recipient_name}</b>\n"
            f"💰 Your wallet was deducted by <b>{amount:,}</b>."
        )
    await update.message.reply_text(result_text, parse_mode="HTML")
    
    try:
        sender_name = display_name_from_db(sender)
        await context.bot.send_message(
            chat_id=recipient["telegram_id"],
            text=f"🎁 <b>{sender_name}</b> sent you 💰 <b>{amount:,}</b> coins!",
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        pass


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return

    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status

    if new_status not in ("member", "administrator"):
        return
    if old_status in ("member", "administrator"):
        return

    chat = result.chat
    if chat.type not in ("group", "supergroup"):
        return

    if new_status in ("member", "administrator"):
        await db.register_group_chat(chat.id, chat.title or "", chat.username or "")

    if new_status not in ("member", "administrator"):
        return
    if old_status in ("member", "administrator"):
        return

    if not LOGGER_GROUP_ID:
        return

    added_by = result.from_user
    added_by_name = display_name(added_by) if added_by else "Unknown"

    try:
        member_count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        member_count = "?"

    username_str = f"@{chat.username}" if chat.username else "PRIVATE GROUP"

    try:
        invite_link = await context.bot.export_chat_invite_link(chat.id)
    except Exception:
        invite_link = "❌ NO INVITE PERMISSION"

    log_text = (
        f"📋 <b>CHAT NAME:</b> {chat.title}\n"
        f"🆔 <b>CHAT ID:</b> <code>{chat.id}</code>\n"
        f"👤 <b>CHAT USERNAME:</b> {username_str}\n"
        f"🔗 <b>CHAT LINK:</b> {invite_link}\n"
        f"👥 <b>GROUP MEMBERS:</b> {member_count}\n"
        f"🤵 <b>ADDED BY:</b> {added_by_name}"
    )

    await _log(context, log_text)


async def handle_forfeit_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dismisses the forfeit confirmation dialog without doing anything."""
    query = update.callback_query
    try:
        await context.bot.delete_message(
            chat_id=query.from_user.id, message_id=query.message.message_id
        )
    except Exception:
        pass
    await query.answer("Cancelled — you stayed in the match.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data

    if data == "tournament_join":
        await handle_tournament_join(update, context)
        return
    if data.startswith("tournament_join:"):
        await handle_tournament_join(update, context)
        return
    if data.startswith("tournament_leave:"):
        await handle_tournament_leave(update, context)
        return
    if data.startswith("tournament_status:"):
        await handle_tournament_status_callback(update, context)
        return
    if data == "detail_help":
        await query.answer()
        await _send_help_message(update, context, via_callback=True)
        return
    if data == "support_channel":
        if SUPPORT_CHANNEL and SUPPORT_CHANNEL.startswith(("http://", "https://")):
            await query.answer()
            await query.message.reply_text("📢 Join our support channel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 Open Support Channel", url=SUPPORT_CHANNEL)]]))
        else:
            await query.answer("Support channel is not configured yet.", show_alert=True)
        return
    if data == "add_me":
        await query.answer("Add this bot to your group, then use /bingo to start a match.", show_alert=True)
        return
    if data.startswith("eco:"):
        await handle_economy_callback(update, context)
        return

    if data.startswith("join:"):
        await handle_join_callback(update, context)
    elif data.startswith("cancel_room:"):
        await handle_cancel_room_callback(update, context)
    elif data.startswith("card:"):
        await handle_card_callback(update, context)
    elif data.startswith("cancel_game:"):
        await handle_cancel_game_callback(update, context)
    elif data.startswith("forfeit_ask:"):
        await handle_forfeit_ask_callback(update, context)
    elif data.startswith("forfeit_confirm:"):
        await handle_forfeit_confirm_callback(update, context)
    elif data.startswith("forfeit_back:"):
        await handle_forfeit_back_callback(update, context)
    elif data.startswith("rematch:"):
        await handle_rematch_callback(update, context)
    elif data.startswith("lb:") or data == "lb_nochat":
        await handle_leaderboard_callback(update, context)
    else:
        await query.answer()


async def post_init(application: Application):
    for attempt in range(1, 6):
        try:
            await db.init_db()
            logger.info("Database initialized.")
            return
        except Exception:
            logger.exception("Database initialization failed (attempt %s/5)", attempt)
            if attempt == 5:
                raise
            await asyncio.sleep(min(30, 2 ** attempt))


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if error:
        logger.error(
            "Unhandled Telegram update error",
            exc_info=(type(error), error, error.__traceback__),
        )
    query = getattr(update, "callback_query", None)
    if query:
        try:
            await query.answer(
                "Something went wrong temporarily. Please try again.",
                show_alert=True,
            )
        except Exception:
            pass


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("bingo", cmd_bingo))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stopbingo", cmd_stopbingo))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("tournament", cmd_tournament))
    app.add_handler(CommandHandler("tournament_add", cmd_tournament_add))
    app.add_handler(CommandHandler("tournament_message", cmd_tournament_message))
    app.add_handler(CommandHandler("tournament_disqualify", cmd_tournament_disqualify))
    app.add_handler(CommandHandler("tournament_start", cmd_tournament_start))
    app.add_handler(CommandHandler("tournament_status", cmd_tournament_status))
    app.add_handler(CommandHandler("announce", cmd_announce_tournament))
    app.add_handler(CommandHandler("playerlist", cmd_playerlist))
    app.add_handler(CommandHandler("cancel_tournament", cmd_cancel_tournament))
    app.add_handler(CommandHandler("give", cmd_give))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("bank", cmd_balance))
    app.add_handler(CommandHandler("economy", cmd_economy))
    app.add_handler(CommandHandler("wallet", cmd_economy))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("transactions", cmd_transactions))
    app.add_handler(CommandHandler("history", cmd_transactions))
    app.add_handler(CommandHandler("deposit", cmd_deposit))
    app.add_handler(CommandHandler("deposite", cmd_deposit))
    app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    app.add_handler(CommandHandler("bet", cmd_bet))
    app.add_handler(CommandHandler("steal", cmd_steal))
    app.add_handler(CommandHandler("ssteal", cmd_steal))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^(?:bbet|bet)(?:\s+.*)?$"), cmd_bet))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^(?:ssteal|steal)(?:\s+.*)?$"), cmd_steal))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(handle_error)

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_webserver()
    main()
