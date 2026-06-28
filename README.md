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
| `/cancel` | Forfeit your current active game |
| `/profile` | View your coins, wins, losses, and streaks |
| `/leaderboard` | Top 10 players |
| `/stopbingo` | Cancel all active rooms in the group (admins only) |

## Tech Stack

- Python 3.11
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21.6
- [Motor](https://motor.readthedocs.io/) v3.4.0 (async MongoDB driver)
- MongoDB (via Atlas or self-hosted)

---

## Local Setup

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
python bot/main.py
```

---

## MongoDB Setup (Free with Atlas)

1. Go to [MongoDB Atlas](https://cloud.mongodb.com)
2. Create a free cluster (M0 Sandbox)
3. Create a database user with read/write access
4. Under **Network Access** → add `0.0.0.0/0` (allow all IPs)
5. Click **Connect → Drivers** and copy the URI
6. Replace `<password>` with your database user's password
7. Add `/velocity_bingo` before the `?` in the URI

**Example URI:**
```
mongodb+srv://myuser:mypassword@cluster0.xxxxx.mongodb.net/velocity_bingo?retryWrites=true&w=majority
```

---

## Deploy to Render (Recommended — Free tier available)

1. Push this repo to GitHub
2. Go to [Render](https://render.com) → **New → Background Worker**
3. Connect your GitHub repo — Render auto-reads `render.yaml`
4. Add environment variables under **Environment**:
   - `TELEGRAM_BOT_TOKEN`
   - `MONGODB_URI`
5. Click **Deploy**

---

## Deploy to Heroku (Docker — Recommended method)

This repo includes a `Dockerfile` and `heroku.yml` for container-based deployment.

### Prerequisites
- [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) installed
- Logged in: `heroku login`

### Steps

```bash
# 1. Create the app
heroku create your-app-name

# 2. Set the stack to container
heroku stack:set container -a your-app-name

# 3. Set environment variables
heroku config:set TELEGRAM_BOT_TOKEN=your_token_here -a your-app-name
heroku config:set MONGODB_URI=your_mongodb_uri_here -a your-app-name

# 4. Push and deploy
git push heroku main

# 5. Scale the worker dyno (free eco dyno)
heroku ps:scale worker=1 -a your-app-name
```

### Alternative: Heroku with Buildpack (no Docker)

If you prefer the classic buildpack approach, skip `heroku.yml` and use:

```bash
heroku create your-app-name
heroku config:set TELEGRAM_BOT_TOKEN=xxx MONGODB_URI=xxx
git push heroku main
heroku ps:scale worker=1
```

> The `Procfile` (`worker: cd bot && python main.py`) handles the entry point automatically.

---

## Project Structure

```
velocity-bingo-bot/
├── bot/
│   ├── main.py         # Entry point, all command handlers
│   ├── database.py     # MongoDB queries via Motor (async)
│   ├── game.py         # Core game logic, card callbacks, rematch
│   ├── rooms.py        # Room create/join/cancel handlers
│   ├── cards.py        # Card generation, bingo detection, keyboards
│   ├── economy.py      # Coins, win/loss tracking
│   ├── leaderboard.py  # Leaderboard formatter
│   ├── models.py       # Constants (WIN_COINS, LINES_TO_WIN, ALL_LINES)
│   └── utils.py        # Display name helpers
├── requirements.txt    # Python dependencies
├── Procfile            # Heroku buildpack worker config
├── runtime.txt         # Python version pin (3.11.9)
├── Dockerfile          # Docker image for Heroku container deploy
├── heroku.yml          # Heroku container stack config
├── render.yaml         # Render deployment config
└── .env.example        # Environment variable template
```

---

## Game Rules

- Max **3 active rooms** per group chat
- Max **1 active game** per player at a time
- Players must `/start` the bot in DM before joining (so cards can be sent privately)
- Win = **5 completed lines** (rows, columns, or diagonals on a 5×5 grid)
- Winner earns **500 coins**
- Forfeit with `/cancel` — opponent wins automatically
- After a game ends, either player can click **🔄 Rematch** to play again instantly
