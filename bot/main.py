import os
import asyncio
import logging
import random
import re
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
from models import LINES_TO_WIN, WIN_COINS, FORFEIT_COST, CANCEL_FREE_THRESHOLD, OWNER_ID, LOGGER_GROUP_ID, SUPPORT_CHANNEL

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

    if not OWNER_ID or user.id != OWNER_ID:
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
    wallet = int(user.get("coins", 0) or 0)
    bank = int(user.get("bank", 0) or 0)
    total = wallet + bank
    await update.message.reply_text(
        f"💰 <b>Bingo Coins</b>\n\n"
        f"👛 Wallet: <b>{wallet:,}</b>\n"
        f"🏦 Bank: <b>{bank:,}</b>\n"
        f"💎 Total Wealth: <b>{total:,}</b>", parse_mode="HTML"
    )


async def cmd_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    if not context.args:
        await update.message.reply_text("Usage: /deposit <amount>\nExample: /deposit 50000\nOr: /deposit all")
        return
    amount = context.args[0]
    wallet = int(user.get("coins", 0) or 0)
    if amount.lower() == "all":
        amount = wallet
    else:
        amount = _parse_amount_arg(amount)
    if not isinstance(amount, int) or amount <= 0:
        await update.message.reply_text("❌ Enter a valid amount.")
        return
    if not await db.deposit_coins(update.effective_user.id, amount):
        await update.message.reply_text(f"❌ You don't have enough wallet coins.\n👛 Wallet: {wallet:,}")
        return
    await update.message.reply_text(f"🏦 <b>Deposit Successful</b>\n\n💰 Deposited: <b>{amount:,}</b>\n🏦 Your coins are now safely in the bank.", parse_mode="HTML")


async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    if not context.args:
        await update.message.reply_text("Usage: /withdraw <amount>\nExample: /withdraw 50000\nOr: /withdraw all")
        return
    amount = context.args[0]
    bank = int(user.get("bank", 0) or 0)
    if amount.lower() == "all":
        amount = bank
    else:
        amount = _parse_amount_arg(amount)
    if not isinstance(amount, int) or amount <= 0:
        await update.message.reply_text("❌ Enter a valid amount.")
        return
    if not await db.withdraw_coins(update.effective_user.id, amount):
        await update.message.reply_text(f"❌ You don't have enough bank coins.\n🏦 Bank: {bank:,}")
        return
    await update.message.reply_text(f"💸 <b>Withdrawal Successful</b>\n\n💰 Withdrawn: <b>{amount:,}</b>\n👛 Coins added to your wallet.", parse_mode="HTML")


async def cmd_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_user(update)
    args = list(context.args)
    # MessageHandler does not populate context.args for plain-text aliases.
    if not args and update.message and update.message.text:
        parts = update.message.text.strip().split()
        if parts and parts[0].lower() == "bbet":
            args = parts[1:]
    if not args:
        await update.message.reply_text(
            "🎰 <b>Bingo Coin Bet</b>\n\n"
            "Use <code>/bet 100000</code> or <code>bbet 100000</code>.\n"
            "Use <code>/bet all</code> or <code>bbet all</code> to bet your whole wallet.\n\n"
            "🏦 Banked coins are protected and cannot be bet directly.\n"
            "🎲 Win = your stake + the same amount as profit.\n"
            "💥 Loss = your stake is lost.", parse_mode="HTML")
        return
    raw = args[0]
    wallet = int(user.get("coins", 0) or 0)
    amount = wallet if raw.lower() == "all" else _parse_amount_arg(raw)
    if not isinstance(amount, int) or amount <= 0:
        await update.message.reply_text("❌ Bet amount must be a positive number or <code>all</code>.", parse_mode="HTML")
        return
    if amount > wallet:
        await update.message.reply_text(f"❌ Not enough Bingo Coins.\n👛 Wallet: <b>{wallet:,}</b>", parse_mode="HTML")
        return
    if not await db.place_bet(update.effective_user.id, amount):
        await update.message.reply_text("❌ Bet could not be placed. Try again.")
        return
    win = random.choice((True, False))
    if win:
        # Stake was already removed; return stake + equal profit.
        await db.resolve_bet(update.effective_user.id, amount * 2)
        await update.message.reply_text(
            f"🎉 <b>BET WON!</b>\n\n🎲 Bet: <b>{amount:,}</b>\n💰 Profit: <b>+{amount:,}</b>\n💎 Total returned: <b>{amount * 2:,}</b>\n\n👛 Balance: <b>{(wallet + amount):,}</b>",
            parse_mode="HTML")
    else:
        remaining = wallet - amount
        await update.message.reply_text(
            f"💥 <b>BET LOST!</b>\n\n🎲 Bet: <b>{amount:,}</b>\n💸 Lost: <b>{amount:,}</b>\n\n👛 Balance: <b>{remaining:,}</b>",
            parse_mode="HTML")


async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_tg = msg.reply_to_message.from_user
        target = await db.get_user(target_tg.id)
        if target:
            return target
        await db.create_user(target_tg.id, target_tg.username, target_tg.first_name)
        return await db.get_user(target_tg.id)
    if context.args:
        raw = context.args[0].strip()
        if raw.startswith("@"):
            return await db.find_user_by_username(raw[1:])
        if raw.isdigit():
            return await db.get_user(int(raw))
    return None


async def cmd_steal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thief = await _ensure_user(update)
    if not context.args and update.message and update.message.text:
        parts = update.message.text.strip().split()
        if parts and parts[0].lower() in ("ssteal",):
            context.args = parts[1:]
    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text("🕵️ Usage: /steal @username or reply to a user's message with /steal\n\nThe target must have used the bot at least once.")
        return
    thief_id = update.effective_user.id
    target_id = target["telegram_id"]
    if thief_id == target_id:
        await update.message.reply_text("❌ You can't steal from yourself!")
        return
    allowed, used = await db.consume_steal_attempt(thief_id)
    if not allowed:
        await update.message.reply_text("🚫 <b>Daily steal limit reached!</b>\nYou can use steal only <b>10 times per day</b>.", parse_mode="HTML")
        return
    target_coins = int(target.get("coins", 0) or 0)
    if target_coins < 1000:
        await update.message.reply_text(f"🛡️ Steal failed! The target doesn't have enough wallet coins to steal.\n\n🎯 Target wallet: <b>{target_coins:,}</b>\n📊 Attempts used: <b>{used}/10</b>", parse_mode="HTML")
        return
    # Random amount is chosen by the bot from the target's wallet balance.
    # Roughly 25%-50%, capped at 100,000; small balances stay proportional.
    upper = min(100000, max(1000, target_coins // 2))
    lower = min(upper, max(1000, target_coins // 4))
    amount = random.randint(lower, upper)
    received = amount * 90 // 100
    if received <= 0:
        await update.message.reply_text("🛡️ Steal failed! The amount was too small.")
        return
    success = await db.perform_steal(thief_id, target_id, amount, received)
    target_name = display_name_from_db(target)
    if not success:
        await update.message.reply_text("🛡️ <b>Steal failed!</b> The target's balance changed before the steal completed.", parse_mode="HTML")
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
        parse_mode="HTML")


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
    
    # OWNER_ID is a minting authority: owner /give never deducts the
    # owner's wallet. Normal members can only give from their own balance.
    if user.id != OWNER_ID and sender["coins"] < amount:
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
    if user.id == OWNER_ID:
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
    
    if user.id == OWNER_ID:
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
    app.add_handler(CommandHandler("deposit", cmd_deposit))
    app.add_handler(CommandHandler("deposite", cmd_deposit))
    app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    app.add_handler(CommandHandler("bet", cmd_bet))
    app.add_handler(CommandHandler("steal", cmd_steal))
    app.add_handler(CommandHandler("ssteal", cmd_steal))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^bbet(?:\s+.*)?$"), cmd_bet))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^ssteal(?:\s+.*)?$"), cmd_steal))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(handle_error)

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_webserver()
    main()
