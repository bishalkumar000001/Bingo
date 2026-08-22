import os

WIN_COINS = 500
FORFEIT_COST = 500 # Coins deducted from a player who forfeits after the 5th number

CANCEL_FREE_THRESHOLD = 5 # Cancellation is free while < this many numbers have been called
LINES_TO_WIN = 5

BINGO_LETTERS = ["B", "I", "N", "G", "O"]

MAX_ROOMS_PER_CHAT = 3

# Support one or multiple owners.
# Preferred Heroku Config Var:
# OWNER_IDS=123456789,987654321
# OWNER_ID is kept as a backwards-compatible fallback.
_owner_ids_raw = os.environ.get("OWNER_IDS", "")
OWNER_IDS = set()
for _value in _owner_ids_raw.replace(";", ",").split(","):
    _value = _value.strip()
    if _value.isdigit():
        OWNER_IDS.add(int(_value))

_legacy_owner = os.environ.get("OWNER_ID", "").strip()
if _legacy_owner.isdigit():
    OWNER_IDS.add(int(_legacy_owner))

# Backwards compatibility for code that still imports OWNER_ID.
OWNER_ID = next(iter(OWNER_IDS), 0)

_logger = os.environ.get("LOGGER_GROUP_ID", "")
LOGGER_GROUP_ID = int(_logger) if _logger else None

SUPPORT_CHANNEL = os.environ.get("SUPPORT_CHANNEL", "")

_tgroup = os.environ.get("TOURNAMENT_GROUP_ID", "").strip()
try:
    TOURNAMENT_GROUP_ID = int(_tgroup) if _tgroup else None
except ValueError:
    TOURNAMENT_GROUP_ID = _tgroup or None

TOURNAMENT_CHANNEL = os.environ.get("TOURNAMENT_CHANNEL", "").strip()
OWNER_CONTACT_URL = os.environ.get("OWNER_CONTACT_URL", SUPPORT_CHANNEL or "https://t.me/").strip()

ALL_LINES = [
    [0, 1, 2, 3, 4],
    [5, 6, 7, 8, 9],
    [10, 11, 12, 13, 14],
    [15, 16, 17, 18, 19],
    [20, 21, 22, 23, 24],
    [0, 5, 10, 15, 20],
    [1, 6, 11, 16, 21],
    [2, 7, 12, 17, 22],
    [3, 8, 13, 18, 23],
    [4, 9, 14, 19, 24],
    [0, 6, 12, 18, 24],
    [4, 8, 12, 16, 20],
]
