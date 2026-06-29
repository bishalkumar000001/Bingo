import os

WIN_COINS = 500
LINES_TO_WIN = 5

BINGO_LETTERS = ["B", "I", "N", "G", "O"]

MAX_ROOMS_PER_CHAT = 3

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

_logger = os.environ.get("LOGGER_GROUP_ID", "")
LOGGER_GROUP_ID = int(_logger) if _logger else None

SUPPORT_CHANNEL = os.environ.get("SUPPORT_CHANNEL", "")

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
