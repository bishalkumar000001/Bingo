# 🎮 Velocity Bingo Bot

A turn-based multiplayer Bingo Telegram bot where players call numbers alternately on each other's 5×5 cards.

## How It Works

- Each player gets a private 5×5 card with numbers 1–25 (shuffled)
- Players take turns **calling** a number on the opponent's card
- The opponent must then **mark** that number on their own card
- First to complete **5 lines** (rows, columns, or diagonals) wins 🏆

## Commands

| Command | Description |
|---|---|
| `/start` | Register and view instructions (use in DM with bot first) |
| `/bingo` | Create a match room (use in a group chat) |
| `/profile` | View your coins, wins, losses, and streaks |
| `/leaderboard` | Top 10 players |
| `/stopbingo` | Cancel all active rooms in the group (admins only) |

## Tech Stack

- Python 3.11
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21.6
- [Motor](https://motor.readthedocs.io/) v3.4.0 (async MongoDB driver)
- MongoDB (via Atlas or self-hosted)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/velocity-bingo-bot.git
cd velocity-bingo-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Get from [@BotFather](https://t.me/BotFather) |
| `MONGODB_URI` | Your MongoDB connection string (Atlas or self-hosted) |

### 4. Run the bot

```bash
cd bot && python main.py
```

---

## Deploy to Render

1. Push this repo to GitHub
2. Go to [Render](https://render.com) → **New → Background Worker**
3. Connect your GitHub repo
4. Render auto-detects `render.yaml` — click **Apply**
5. Add your environment variables under **Environment**:
   - `TELEGRAM_BOT_TOKEN`
   - `MONGODB_URI`
6. Click **Deploy**

---

## Deploy to Heroku

1. Push this repo to GitHub (or use Heroku CLI)
2. Create a new Heroku app:

```bash
heroku create your-app-name
```

3. Set environment variables:

```bash
heroku config:set TELEGRAM_BOT_TOKEN=your_token_here
heroku config:set MONGODB_URI=your_mongodb_uri_here
```

4. Deploy:

```bash
git push heroku main
```

5. Scale the worker dyno:

```bash
heroku ps:scale worker=1
```

> **Note:** The `Procfile` is already configured as `worker: cd bot && python main.py`.
> Do **not** use a `web` dyno — this is a bot, not a web server.

---

## MongoDB Setup (Free with Atlas)

1. Go to [MongoDB Atlas](https://cloud.mongodb.com)
2. Create a free cluster (M0 Sandbox)
3. Create a database user with read/write access
4. Whitelist `0.0.0.0/0` (all IPs) under **Network Access**
5. Click **Connect → Drivers** and copy the URI
6. Replace `<password>` in the URI with your database user's password
7. Append `/velocity_bingo` before the `?` in the URI

Example:
```
mongodb+srv://myuser:mypassword@cluster0.xxxxx.mongodb.net/velocity_bingo?retryWrites=true&w=majority
```

---

## Project Structure

```
velocity-bingo-bot/
├── bot/
│   ├── main.py         # Entry point, command handlers
│   ├── database.py     # All MongoDB queries (Motor)
│   ├── game.py         # Core game logic and card callbacks
│   ├── rooms.py        # Room creation/join/cancel handlers
│   ├── cards.py        # Card generation, bingo detection, keyboards
│   ├── economy.py      # Coins and win/loss stats
│   ├── leaderboard.py  # Leaderboard formatter
│   ├── models.py       # Constants (WIN_COINS, LINES_TO_WIN, ALL_LINES)
│   └── utils.py        # Display name helpers
├── requirements.txt
├── Procfile            # Heroku worker config
├── runtime.txt         # Python version for Heroku
├── render.yaml         # Render deployment config
└── .env.example        # Example environment variables
```

## Rules / Constraints

- Max **3 active rooms** per group
- Max **1 active game** per player at a time
- Players must `/start` the bot in DM before joining (so cards can be sent privately)
- Win = **5 completed lines** (rows, columns, or diagonals)
- Winner earns **500 coins**
