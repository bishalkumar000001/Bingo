import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest, Forbidden

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
    cmd_tournament, cmd_tournamentinfo, cmd_tjoin, cmd_announce, cmd_tadd, cmd_tstart,
    handle_tournament_wizard_callback, handle_tournament_join,
    handle_tournament_card, handle_tournament_disqualify,
    handle_announce_callback, handle_tstart_callback,
    handle_tournament_wizard_message, recover_tournaments,
)
from utils import display_name_from_db, display_name
from models import LINES_TO_WIN, WIN_COINS, FORFEIT_COST, CANCEL_FREE_THRESHOLD, OWNER_ID, OWNER_IDS, LOGGER_GROUP_ID, SUPPORT_CHANNEL
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _build_start_text(user):
    name = user.full_name or user.first_name or "Player"
    return f"""🎮 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝘁𝗵𝗲 𝗨𝗹𝘁𝗶𝗺𝗮𝘁𝗲 𝗕𝗶𝗻𝗴𝗼 𝗚𝗮𝗺𝗲 𝗕𝗼𝘁! 🎉
{name}

𝗥𝗲𝗮𝗱𝘆 𝘁𝗼 𝗽𝗹𝗮𝘆 𝗕𝗶𝗻𝗴𝗼 𝘄𝗶𝘁𝗵 𝘆𝗼𝘂𝗿 𝗳𝗿𝗶𝗲𝗻𝗱𝘀 𝗮𝗻𝗱 𝗼𝘁𝗵𝗲𝗿 𝗽𝗹𝗮𝘆𝗲𝗿𝘀? 𝗜𝘁'𝘀 𝗲𝗮𝘀𝘆, 𝗳𝘂𝗻 & 𝗲𝘅𝗰𝗶𝘁𝗶𝗻𝗴! 🔥

╭─❖ 🎯 𝗛𝗼𝘄 𝘁𝗼 𝗣𝗹𝗮𝘆? ❖─╮

🔢 𝗦𝘁𝗮𝗿𝘁 𝗮 𝟭𝘃𝟭 𝗴𝗮𝗺𝗲 𝗮𝗻𝗱 𝗰𝗵𝗮𝗹𝗹𝗲𝗻𝗴𝗲 𝗮𝗻𝗼𝘁𝗵𝗲𝗿 𝗽𝗹𝗮𝘆𝗲𝗿.
🎲 𝗕𝗼𝘁𝗵 𝗽𝗹𝗮𝘆𝗲𝗿𝘀 𝗴𝗲𝘁 𝗮 𝟱×𝟱 𝗕𝗶𝗻𝗴𝗼 𝗰𝗮𝗿𝗱 𝘄𝗶𝘁𝗵 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝟭–𝟮𝟱.
👆 𝗧𝗮𝗸𝗲 𝘁𝘂𝗿𝗻𝘀 𝗰𝗵𝗼𝗼𝘀𝗶𝗻𝗴 𝗻𝘂𝗺𝗯𝗲𝗿𝘀.
✅ 𝗧𝗵𝗲 𝗰𝗵𝗼𝘀𝗲𝗻 𝗻𝘂𝗺𝗯𝗲𝗿 𝗶𝘀 𝗺𝗮𝗿𝗸𝗲𝗱 𝗼𝗻 𝗯𝗼𝘁𝗵 𝗰𝗮𝗿𝗱𝘀.

🏆 𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝟱 𝗹𝗶𝗻𝗲𝘀 — 𝗥𝗼𝘄𝘀, 𝗖𝗼𝗹𝘂𝗺𝗻𝘀 𝗼𝗿 𝗗𝗶𝗮𝗴𝗼𝗻𝗮𝗹𝘀 — 𝘁𝗼 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝗕𝗜𝗡𝗚𝗢. 𝗧𝗵𝗲 𝗳𝗶𝗿𝘀𝘁 𝗽𝗹𝗮𝘆𝗲𝗿 𝘁𝗼 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝗶𝘁 𝘄𝗶𝗻𝘀! 🎊

╰─❖ 💰 𝗣𝗹𝗮𝘆 & 𝗘𝗮𝗿𝗻 ❖─╯

🏅 𝗪𝗶𝗻 𝗺𝗮𝘁𝗰𝗵𝗲𝘀 𝗮𝗻𝗱 𝗲𝗮𝗿𝗻 𝗕𝗶𝗻𝗴𝗼 𝗖𝗼𝗶𝗻𝘀
📊 𝗖𝗵𝗲𝗰𝗸 𝘆𝗼𝘂𝗿 𝗦𝘁𝗮𝘁𝘀 & 𝗪𝗶𝗻𝘀
🥇 𝗖𝗹𝗶𝗺𝗯 𝘁𝗵𝗲 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱
🏆 𝗝𝗼𝗶𝗻 𝗧𝗼𝘂𝗿𝗻𝗮𝗺𝗲𝗻𝘁𝘀 & 𝗰𝗼𝗺𝗽𝗲𝘁𝗲 𝗳𝗼𝗿 𝗿𝗲𝘄𝗮𝗿𝗱𝘀!

✨ 𝗡𝗼 𝗰𝗼𝗺𝗽𝗹𝗶𝗰𝗮𝘁𝗲𝗱 𝗿𝘂𝗹𝗲𝘀 — 𝗷𝘂𝘀𝘁 𝗽𝗹𝗮𝘆, 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝘆𝗼𝘂𝗿 𝗕𝗜𝗡𝗚𝗢 & 𝗵𝗮𝘃𝗲 𝗳𝘂𝗻! ❤️

👇 Start playing with your friends. 🎮
/bingo = to start the match.
/leaderboard = rankings of the top ten users
/profile = for your stats
/give username amount = to give coins to your friend or cab be use for bet
/cancel to stop the current match upto four chances it is free after four chances it cost 500 for cancel

👑 𝗣𝗹𝗮𝘆 • 𝗪𝗶𝗻 • 𝗕𝗲𝗰𝗼𝗺𝗲 𝘁𝗵𝗲 𝗕𝗶𝗻𝗴𝗼 𝗖𝗵𝗮𝗺𝗽𝗶𝗼𝗻! 🏆""".strip()

async def _build_start_keyboard(context):
    me = await context.bot.get_me()
    add_url = f"https://t.me/{me.username}?startgroup=true"
    support_url = SUPPORT_CHANNEL or "https://t.me/"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD ME TO GROUP", url=add_url)],
        [InlineKeyboardButton("📢 SUPPORT & UPDATES", url=support_url)],
        [InlineKeyboardButton("❓ HELP / HOW TO PLAY", callback_data="start_help")],
    ])


async def _build_help_text(user):
    name = user.full_name or user.first_name or "Player"
    return f"""🎮 𝗪𝗲𝗹𝗰𝗼𝗺𝗲, {name}!
𝗩𝗲𝗹𝗼𝗰𝗶𝘁𝘆 𝗕𝗶𝗻𝗴𝗼 𝗶𝘀 𝗮 𝗳𝘂𝗻 𝟭𝘃𝟭 𝗕𝗶𝗻𝗴𝗼 𝗴𝗮𝗺𝗲 𝘄𝗵𝗲𝗿𝗲 𝘆𝗼𝘂 𝗰𝗮𝗻 𝗰𝗵𝗮𝗹𝗹𝗲𝗻𝗴𝗲 𝗼𝘁𝗵𝗲𝗿 𝗽𝗹𝗮𝘆𝗲𝗿𝘀, 𝘄𝗶𝗻 𝗺𝗮𝘁𝗰𝗵𝗲𝘀, 𝗲𝗮𝗿𝗻 𝗰𝗼𝗶𝗻𝘀 𝗮𝗻𝗱 𝗯𝗲𝗰𝗼𝗺𝗲 𝗮 𝗰𝗵𝗮𝗺𝗽𝗶𝗼𝗻! 👑

🎯 𝗦𝘁𝗮𝗿𝘁𝗶𝗻𝗴 𝗮 𝗚𝗮𝗺𝗲

🎮 𝗖𝗿𝗲𝗮𝘁𝗲 𝗼𝗿 𝗷𝗼𝗶𝗻 𝗮 𝟭𝘃𝟭 𝗺𝗮𝘁𝗰𝗵 𝘄𝗶𝘁𝗵 𝗮𝗻𝗼𝘁𝗵𝗲𝗿 𝗽𝗹𝗮𝘆𝗲𝗿.
🤝 𝗢𝗻𝗰𝗲 𝗯𝗼𝘁𝗵 𝗽𝗹𝗮𝘆𝗲𝗿𝘀 𝗷𝗼𝗶𝗻, 𝘁𝗵𝗲 𝗴𝗮𝗺𝗲 𝗯𝗲𝗴𝗶𝗻𝘀.
🔢 𝗘𝗮𝗰𝗵 𝗽𝗹𝗮𝘆𝗲𝗿 𝗴𝗲𝘁𝘀 𝗮 𝟱×𝟱 𝗕𝗶𝗻𝗴𝗼 𝗰𝗮𝗿𝗱 𝘄𝗶𝘁𝗵 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝟭–𝟮𝟱.

📩 𝗦𝘁𝗮𝗿𝘁 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗶𝗻 𝗽𝗿𝗶𝘃𝗮𝘁𝗲 𝘂𝘀𝗶𝗻𝗴 /𝘀𝘁𝗮𝗿𝘁 𝘁𝗼 𝗿𝗲𝗰𝗲𝗶𝘃𝗲 𝘆𝗼𝘂𝗿 𝗰𝗮𝗿𝗱 𝗮𝗻𝗱 𝗴𝗮𝗺𝗲 𝘂𝗽𝗱𝗮𝘁𝗲𝘀!

🔄 𝗛𝗼𝘄 𝘁𝗵𝗲 𝗚𝗮𝗺𝗲 𝗪𝗼𝗿𝗸𝘀

👆 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 𝘁𝗮𝗸𝗲 𝘁𝘂𝗿𝗻𝘀 𝗰𝗵𝗼𝗼𝘀𝗶𝗻𝗴 𝗻𝘂𝗺𝗯𝗲𝗿𝘀.
✅ 𝗖𝗮𝗹𝗹𝗲𝗱 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗮𝗿𝗲 𝗺𝗮𝗿𝗸𝗲𝗱 𝗼𝗻 𝘁𝗵𝗲 𝗕𝗶𝗻𝗴𝗼 𝗰𝗮𝗿𝗱𝘀.
🧠 𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝘆𝗼𝘂𝗿 𝗹𝗶𝗻𝗲𝘀 𝗯𝗲𝗳𝗼𝗿𝗲 𝘆𝗼𝘂𝗿 𝗼𝗽𝗽𝗼𝗻𝗲𝗻𝘁 𝗮𝗻𝗱 𝗴𝗲𝘁 𝗰𝗹𝗼𝘀𝗲𝗿 𝘁𝗼 𝗕𝗜𝗡𝗚𝗢! 🔥

🏆 𝗛𝗼𝘄 𝘁𝗼 𝗪𝗶𝗻

𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝟱 𝗳𝘂𝗹𝗹 𝗹𝗶𝗻𝗲𝘀 𝗼𝗻 𝘆𝗼𝘂𝗿 𝗕𝗶𝗻𝗴𝗼 𝗰𝗮𝗿𝗱!

➖ 𝗥𝗼𝘄𝘀 — 𝗟𝗲𝗳𝘁 𝘁𝗼 𝗿𝗶𝗴𝗵𝘁
⬇️ 𝗖𝗼𝗹𝘂𝗺𝗻𝘀 — 𝗧𝗼𝗽 𝘁𝗼 𝗯𝗼𝘁𝘁𝗼𝗺
✖️ 𝗗𝗶𝗮𝗴𝗼𝗻𝗮𝗹𝘀 — 𝗔𝗰𝗿𝗼𝘀𝘀 𝘁𝗵𝗲 𝗰𝗮𝗿𝗱

🎉 𝗧𝗵𝗲 𝗳𝗶𝗿𝘀𝘁 𝗽𝗹𝗮𝘆𝗲𝗿 𝘁𝗼 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝗕-𝗜-𝗡-𝗚-𝗢 𝘄𝗶𝗻𝘀 𝘁𝗵𝗲 𝗺𝗮𝘁𝗰𝗵! 👑🏆

💰 𝗖𝗼𝗶𝗻𝘀 & 𝗪𝗶𝗻𝘀

🏅 𝗪𝗶𝗻 𝗺𝗮𝘁𝗰𝗵𝗲𝘀 𝘁𝗼 𝗲𝗮𝗿𝗻 𝗕𝗶𝗻𝗴𝗼 𝗖𝗼𝗶𝗻𝘀 🪙
📈 𝗬𝗼𝘂𝗿 𝘀𝘁𝗮𝘁𝘀 𝗮𝗻𝗱 𝗴𝗮𝗺𝗲 𝗿𝗲𝘀𝘂𝗹𝘁𝘀 𝗮𝗿𝗲 𝘀𝗮𝘃𝗲𝗱 𝗮𝘂𝘁𝗼𝗺𝗮𝘁𝗶𝗰𝗮𝗹𝗹𝘆.
🔥 𝗞𝗲𝗲𝗽 𝘄𝗶𝗻𝗻𝗶𝗻𝗴 𝗮𝗻𝗱 𝗰𝗹𝗶𝗺𝗯 𝗵𝗶𝗴𝗵𝗲𝗿 

👤 𝗬𝗼𝘂𝗿 𝗣𝗿𝗼𝗳𝗶𝗹𝗲

𝗖𝗵𝗲𝗰𝗸 𝘆𝗼𝘂𝗿:
• 🪙 𝗕𝗶𝗻𝗴𝗼 𝗖𝗼𝗶𝗻𝘀
• 🎮 𝗧𝗼𝘁𝗮𝗹 𝗚𝗮𝗺𝗲𝘀
• 🏆 𝗧𝗼𝘁𝗮𝗹 𝗪𝗶𝗻𝘀
• 📈 𝗚𝗮𝗺𝗲 𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝘀

🥇 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱

𝗖𝗼𝗺𝗽𝗲𝘁𝗲 𝘄𝗶𝘁𝗵 𝗼𝘁𝗵𝗲𝗿 𝗽𝗹𝗮𝘆𝗲𝗿𝘀 𝗮𝗻𝗱 𝗳𝗶𝗴𝗵𝘁 𝗳𝗼𝗿 𝘁𝗵𝗲 #𝟭 𝘀𝗽𝗼𝘁! 👑🔥

🏆 𝗧𝗼𝘂𝗿𝗻𝗮𝗺𝗲𝗻𝘁𝘀

🎯 𝗝𝗼𝗶𝗻 𝘀𝗽𝗲𝗰𝗶𝗮𝗹 𝘁𝗼𝘂𝗿𝗻𝗮𝗺𝗲𝗻𝘁𝘀 𝗮𝗻𝗱 𝗰𝗼𝗺𝗽𝗲𝘁𝗲 𝗶𝗻 𝗲𝘅𝗰𝗶𝘁𝗶𝗻𝗴 𝗿𝗼𝘂𝗻𝗱𝘀!

➡️ 𝗪𝗶𝗻 𝘆𝗼𝘂𝗿 𝗺𝗮𝘁𝗰𝗵
➡️ 𝗠𝗼𝘃𝗲 𝘁𝗼 𝘁𝗵𝗲 𝗻𝗲𝘅𝘁 𝗿𝗼𝘂𝗻𝗱
➡️ 𝗥𝗲𝗮𝗰𝗵 𝘁𝗵𝗲 𝗙𝗶𝗻𝗮𝗹
👑 𝗕𝗲𝗰𝗼𝗺𝗲 𝘁𝗵𝗲 𝗧𝗼𝘂𝗿𝗻𝗮𝗺𝗲𝗻𝘁 𝗖𝗵𝗮𝗺𝗽𝗶𝗼𝗻!

❌ 𝗖𝗮𝗻𝗰𝗲𝗹𝗹𝗶𝗻𝗴 & 𝗙𝗮𝗶𝗿 𝗣𝗹𝗮𝘆

𝗜𝗳 𝘆𝗼𝘂 𝗰𝗮𝗻'𝘁 𝗰𝗼𝗻𝘁𝗶𝗻𝘂𝗲, 𝘂𝘀𝗲 𝘁𝗵𝗲 𝗖𝗮𝗻𝗰𝗲𝗹 𝗼𝗽𝘁𝗶𝗼𝗻 𝘄𝗵𝗲𝗻 𝗮𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲. 🤝
⚠️ 𝗣𝗹𝗮𝘆 𝗳𝗮𝗶𝗿𝗹𝘆 𝗮𝗻𝗱 𝗱𝗼𝗻'𝘁 𝗸𝗲𝗲𝗽 𝘆𝗼𝘂𝗿 𝗼𝗽𝗽𝗼𝗻𝗲𝗻𝘁 𝘄𝗮𝗶𝘁𝗶𝗻𝗴!

📌 𝗜𝗺𝗽𝗼𝗿𝘁𝗮𝗻𝘁 𝗥𝘂𝗹𝗲𝘀

🤝 𝗥𝗲𝘀𝗽𝗲𝗰𝘁 𝗼𝘁𝗵𝗲𝗿 𝗽𝗹𝗮𝘆𝗲𝗿𝘀
⏳ 𝗣𝗹𝗮𝘆 𝘆𝗼𝘂𝗿 𝘁𝘂𝗿𝗻𝘀 𝗼𝗻 𝘁𝗶𝗺𝗲
🚫 𝗗𝗼𝗻'𝘁 𝗮𝗯𝘂𝘀𝗲 𝗼𝗿 𝗲𝘅𝗽𝗹𝗼𝗶𝘁 𝘁𝗵𝗲 𝗴𝗮𝗺𝗲
❤️ 𝗛𝗮𝘃𝗲 𝗳𝘂𝗻 𝗮𝗻𝗱 𝗲𝗻𝗷𝗼𝘆!

✨ 𝗤𝘂𝗶𝗰𝗸 𝗦𝘁𝗮𝗿𝘁

𝟭️ 𝗦𝘁𝗮𝗿𝘁 𝘁𝗵𝗲 𝗕𝗼𝘁 → 𝟮️ 𝗝𝗼𝗶𝗻 𝗮 𝗠𝗮𝘁𝗰𝗵 → 𝟯️ 𝗣𝗹𝗮𝘆 → 𝟰️ 𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲 𝗕𝗜𝗡𝗚𝗢 → 𝟱️ 𝗪𝗜𝗡! 🏆 

╭───── ✨ ─────╮
🎮 𝗣𝗹𝗮𝘆 𝗦𝗺𝗮𝗿𝘁
🏆 𝗪𝗶𝗻 𝗕𝗶𝗴
👑 𝗕𝗲𝗰𝗼𝗺𝗲 𝗮 𝗟𝗲𝗴𝗲𝗻𝗱
╰───── ✨ ─────╯""".strip()

async def _send_optional_photo(message, photo_url):
    if photo_url:
        try:
            await message.reply_photo(photo=photo_url)
        except Exception as exc:
            logger.warning("Could not send configured photo: %s", exc)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username, user.first_name)

    await _send_optional_photo(update.message, os.getenv("START_PHOTO_URL", "").strip())
    text = await _build_start_text(user)
    keyboard = await _build_start_keyboard(context)
    await update.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await db.get_user(user.id):
        await db.create_user(user.id, user.username, user.first_name)

    await _send_optional_photo(update.message, os.getenv("HELP_PHOTO_URL", "").strip())
    text = await _build_help_text(user)
    await update.message.reply_text(text, disable_web_page_preview=True)

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
    coins = player["coins"]

    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Profile — {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Coins: <b>{coins:,}</b>\n"
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

    if not OWNER_IDS or user.id not in OWNER_IDS:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    source = update.message.reply_to_message
    if not source and not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "• Reply to a message with /broadcast to forward it to all users\n"
            "• /broadcast <text> to send a plain message"
        )
        return

    user_ids = await db.get_all_user_ids()
    sent = failed = 0

    status_msg = await update.message.reply_text(
        f"📡 Broadcasting to <b>{len(user_ids)}</b> users...", parse_mode="HTML"
    )

    for uid in user_ids:
        try:
            if source:
                await source.copy(chat_id=uid)
            else:
                await context.bot.send_message(
                    chat_id=uid,
                    text=" ".join(context.args),
                    parse_mode="HTML",
                )
            sent += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    try:
        await status_msg.edit_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Broadcast Complete!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📨 Sent: <b>{sent}</b>\n"
            f"❌ Failed: <b>{failed}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
        )
    except BadRequest:
        pass


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
    
    if user.id not in OWNER_IDS and sender["coins"] < amount:
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
    if user.id in OWNER_IDS:
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
    
    await update.message.reply_text(
        f"✅ Transfer successful!\n\n"
        f"Sent: 💰 <b>{amount:,}</b> coins\n"
        f"To: <b>{recipient_name}</b>",
        parse_mode="HTML",
    )
    
    try:
        sender_name = display_name_from_db(sender)
        await context.bot.send_message(
            chat_id=recipient["telegram_id"],
            text=f"🎁 <b>{sender_name}</b> sent you 💰 <b>{amount:,}</b> coins!",
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        pass


async def register_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    try:
        await db.register_group(chat.id, chat.title or "", chat.username or "")
    except Exception:
        pass


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not LOGGER_GROUP_ID:
        return

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
    try:
        await db.register_group(chat.id, chat.title or "", chat.username or "")
    except Exception:
        pass

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
    data = query.data

    if data.startswith("tw:"):
        await handle_tournament_wizard_callback(update, context)
    elif data.startswith("tann:"):
        await handle_announce_callback(update, context)
    elif data.startswith("tjoin:"):
        await handle_tournament_join(update, context)
    elif data.startswith("tstart:"):
        await handle_tstart_callback(update, context)
    elif data.startswith("tcard:"):
        await handle_tournament_card(update, context)
    elif data.startswith("tdq:"):
        await handle_tournament_disqualify(update, context)
    elif data.startswith("join:"):
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
    elif data == "start_help":
        user = query.from_user
        # Use exactly the same dynamic help text as the /help command.
        text = await _build_help_text(user)
        try:
            await query.message.edit_text(text, parse_mode="HTML", reply_markup=await _build_start_keyboard(context), disable_web_page_preview=True)
        except BadRequest:
            pass
        await query.answer()
    else:
        await query.answer()



async def post_init(application: Application):
    await db.init_db()
    logger.info("Database initialized.")
    try:
        await recover_tournaments(application)
    except Exception:
        logger.exception("Tournament recovery failed")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(64)
        .post_init(post_init)
        .build()
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tournament_wizard_message), group=-5)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, register_group_activity), group=-10)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("bingo", cmd_bingo))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stopbingo", cmd_stopbingo))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("give", cmd_give))
    app.add_handler(CommandHandler("tournament", cmd_tournament))
    app.add_handler(CommandHandler("tournamentinfo", cmd_tournamentinfo))
    app.add_handler(CommandHandler("tjoin", cmd_tjoin))
    app.add_handler(CommandHandler("announce", cmd_announce))
    app.add_handler(CommandHandler("tadd", cmd_tadd))
    app.add_handler(CommandHandler("tstart", cmd_tstart))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🎮 Velocity Bingo Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
