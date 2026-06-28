# Velocity Bingo Bot

A turn-based multiplayer Bingo Telegram Bot where players call numbers alternately on each other's cards.

## Run & Operate

- `cd bot && python main.py` — run the Telegram bot (managed via workflow "Velocity Bingo Bot")
- Required env: `TELEGRAM_BOT_TOKEN` — your bot token from @BotFather

## Stack

- Python 3.11
- python-telegram-bot v21.6 (async)
- aiosqlite + SQLite (velocity_bingo.db)

## Where things live

- `bot/main.py` — entry point, command handlers
- `bot/database.py` — all SQLite queries
- `bot/game.py` — core game logic and card callbacks
- `bot/rooms.py` — room creation/join/cancel handlers
- `bot/cards.py` — card generation, bingo detection, keyboard builder
- `bot/economy.py` — coins and win/loss stats
- `bot/leaderboard.py` — leaderboard formatter
- `bot/models.py` — constants (WIN_COINS, LINES_TO_WIN, ALL_LINES)
- `bot/utils.py` — display name helpers
- `bot/velocity_bingo.db` — SQLite database (auto-created on first run)

## Architecture decisions

- Single live group message is edited after every move (no spam)
- Private card keyboards sent via DM — only owner can interact
- Phase-based turn system: 'call' → caller picks a number; 'mark' → opponent marks it
- All 25 numbers (1–25) appear on every card, shuffled per player
- 5 completed lines (rows/cols/diagonals) = BINGO = win
- Anti-cheat: every button press validated server-side (turn, phase, ownership)

## Product

- /start — register and see instructions (send in DM to bot first)
- /bingo — create a room in a group (max 3 per group)
- /profile — view coins, wins, losses, streaks
- /leaderboard — top 10 players
- /stopbingo — admin-only: cancel all active rooms

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Players must /start the bot in DM before cards can be sent privately
- Max 3 rooms per group, 1 active game per player
- Bot must be added to the group to receive /bingo commands

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
