# Velocity Bingo — Heroku Deployment

This project is a Telegram bot deployed as a Heroku **worker**. It uses MongoDB for persistent data and long polling for Telegram updates.

## Required Config Vars

- `TELEGRAM_BOT_TOKEN` — BotFather token
- `MONGODB_URI` — MongoDB Atlas connection string
- `OWNER_ID` — your Telegram numeric user ID (or use `OWNER_IDS` for multiple owners)

## Existing optional Config Vars

- `OWNER_IDS` — comma-separated owner IDs
- `LOGGER_GROUP_ID` — log group ID
- `SUPPORT_CHANNEL` — support channel/link
- `TOURNAMENT_GROUP_ID` — official tournament game group
- `TOURNAMENT_CHANNEL` — official tournament announcement channel
- `OWNER_CONTACT_URL` — link used by paid tournament contact button

## Heroku

1. Create/open your Heroku app.
2. Put this repository at the repository root (the folder containing `Procfile`, `requirements.txt`, `runtime.txt`, and `bot/`).
3. Set the Config Vars under **Settings → Config Vars**.
4. Deploy the repository.
5. Scale **worker = 1** under Resources.
6. Check **More → View logs**.

Expected startup log:

`🎮 Velocity Bingo Bot is starting...`

The bot starts its health web server in a background thread and runs Telegram polling in the worker process.

## Important

Do not run multiple worker dynos for the same Telegram bot token. Multiple polling processes can conflict.
