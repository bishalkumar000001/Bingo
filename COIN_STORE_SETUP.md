# Velocity Bingo Coin Store setup

This project now serves the coin store at `/buy-coins`, preserves the existing root health response, and exposes `/health`. The economy keyboard shows only the `🪙 Buy Coins` URL button. Manual economy commands are retained.

## Required Heroku Config Vars

- `TELEGRAM_BOT_TOKEN`: existing bot token (required on both web and worker dynos).
- `TELEGRAM_BOT_USERNAME`: bot username without `@`.
- `MONGODB_URI`: existing MongoDB connection string, shared by web and worker dynos.
- `PUBLIC_BASE_URL`: `https://bingos-9b203c93cae2.herokuapp.com` (or your deployed domain).
- `BUY_COINS_URL`: `https://bingos-9b203c93cae2.herokuapp.com/buy-coins`.

In BotFather, configure the domain for the Telegram Login Widget using `/setdomain` and your deployed domain. The login widget will not validate until the bot's domain is configured.

## Heroku process types

Deploy both a `web` dyno (website) and a `worker` dyno (bot polling). Do not run two worker dynos with the same bot token. For container deploys, `heroku.yml` now defines both process types. For buildpack deploys, `Procfile` defines both.

## Payment behavior

The store creates Telegram Stars (`XTR`) invoice links. The bot credits coins only on Telegram's `successful_payment` update, checks the package and Stars amount, and uses a charge ID guard to avoid duplicate coin credits. Purchases require an existing Bingo wallet, so the player must send `/start` to the bot first.

Default package values are in `bot/webserver.py` (`COIN_PACKAGES`) and mirrored in `bot/main.py` for payment validation. Keep both definitions synchronized when changing package prices or coin amounts. Coins are virtual game credits only; this implementation has no cash withdrawal or redemption.
