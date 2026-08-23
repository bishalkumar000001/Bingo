from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from database import get_user_rank_from_player


def _font(size: int, bold: bool = False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit(text: str, limit: int = 22) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fit_font(draw, text: str, max_width: int, start_size: int, min_size: int, bold: bool = True):
    """Return the largest font size that fits inside max_width."""
    text = str(text or "")
    for size in range(start_size, min_size - 1, -1):
        font = _font(size, bold)
        box = draw.textbbox((0, 0), text, font=font)
        if (box[2] - box[0]) <= max_width:
            return font
    return _font(min_size, bold)


def _rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


async def build_profile_image(player: dict, avatar_bytes=None) -> BytesIO:
    """Create a rectangular neon profile card from live player data."""
    width, height = 1200, 820
    image = Image.new("RGB", (width, height), "#070814")
    draw = ImageDraw.Draw(image)

    # Main rectangular card.
    _rounded(draw, (28, 25, width - 28, height - 25), 42, fill="#0d1022", outline="#2b4ea0", width=3)

    # Decorative neon geometry.
    draw.ellipse((-150, -150, 180, 180), outline="#6624d8", width=38)
    draw.ellipse((1040, -120, 1370, 210), outline="#188aff", width=38)
    draw.ellipse((-120, 650, 210, 980), outline="#2431a8", width=30)
    draw.ellipse((1020, 620, 1370, 970), outline="#9b25d9", width=30)
    for i in range(4):
        x = 970 + i * 38
        draw.line((x, 72, x + 85, 15), fill="#252c76", width=3)

    title_font = _font(68, True)
    username_font = _font(34, True)
    label_font = _font(19, True)
    value_font = _font(28, True)
    big_value_font = _font(60, True)
    stat_label_font = _font(18, True)
    stat_value_font = _font(38, True)
    footer_font = _font(22, True)

    # Header.
    draw.text((width // 2, 88), "MY PROFILE", font=title_font, anchor="mm", fill="#f2f5ff")
    draw.text((width // 2, 142), "VELOCITY BINGO PLAYER CARD", font=_font(17, True), anchor="mm", fill="#8295d8")
    _rounded(draw, (440, 165, 760, 171), 3, fill="#566dff")

    username = player.get("username") or f"player_{player.get('telegram_id', '')}"
    username = "@" + str(username).lstrip("@")
    coins = int(player.get("coins", 0) or 0)
    games = int(player.get("games_played", 0) or 0)
    wins = int(player.get("wins", 0) or 0)
    losses = int(player.get("losses", 0) or 0)
    streak = int(player.get("current_streak", 0) or 0)
    longest = int(player.get("longest_streak", 0) or 0)
    win_rate = (wins / games * 100) if games else 0.0
    rank = await get_user_rank_from_player(player)
    rank_text = f"#{rank}" if rank else "UNRANKED"

    # Automatically resize long usernames so they never get cut off.
    username_font = _fit_font(
        draw, username, max_width=320, start_size=34, min_size=16, bold=True
    )

    # Profile avatar. Use Telegram profile photo when avatar bytes are available.
    avatar_box = (70, 220, 320, 470)
    draw.ellipse(avatar_box, fill="#101633", outline="#5a62ff", width=7)
    if avatar_bytes:
        try:
            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGB")
            side = min(avatar.size)
            left = (avatar.width - side) // 2
            top = (avatar.height - side) // 2
            avatar = avatar.crop((left, top, left + side, top + side)).resize((230, 230), Image.LANCZOS)

            # Circular alpha mask keeps the photo inside the profile circle.
            mask = Image.new("L", (230, 230), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 229, 229), fill=255)
            image.paste(avatar, (80, 230), mask)
            draw.ellipse((70, 220, 320, 470), outline="#8b6cff", width=7)
        except Exception:
            # Fall back to the default avatar icon if Telegram photo data cannot be read.
            draw.ellipse((145, 270, 245, 370), fill="#4c77df")
            _rounded(draw, (105, 375, 285, 455), 75, fill="#493bb7")
    else:
        # Default avatar icon when the user has no Telegram profile photo.
        draw.ellipse((145, 270, 245, 370), fill="#4c77df")
        _rounded(draw, (105, 375, 285, 455), 75, fill="#493bb7")

    # Identity panel.
    _rounded(draw, (355, 225, 735, 330), 20, fill="#111833", outline="#2b9eff", width=2)
    draw.text((385, 277), username, font=username_font, anchor="lm", fill="#f4f6ff")
    draw.text((365, 375), "USER ID", font=label_font, anchor="lm", fill="#8997c8")
    draw.text((560, 375), str(player.get("telegram_id", "-")), font=value_font, anchor="lm", fill="#e8edff")
    draw.line((365, 405, 720, 405), fill="#26305d", width=2)
    draw.text((365, 445), "ACCOUNT STATUS", font=label_font, anchor="lm", fill="#8997c8")
    status_font = _fit_font(draw, "ACTIVE PLAYER", max_width=150, start_size=28, min_size=16, bold=True)
    draw.text((565, 445), "ACTIVE PLAYER", font=status_font, anchor="lm", fill="#5de3a1")

    # Coin balance panel.
    _rounded(draw, (770, 220, 1130, 390), 24, fill="#171326", outline="#d78c29", width=2)
    draw.text((950, 260), "COIN BALANCE", font=_font(23, True), anchor="mm", fill="#c5c9de")
    coin_text = f"${coins:,}"
    coin_font = _fit_font(draw, coin_text, max_width=320, start_size=60, min_size=26, bold=True)
    draw.text((950, 335), coin_text, font=coin_font, anchor="mm", fill="#ffc74d")

    # Rank panel.
    _rounded(draw, (770, 410, 1130, 555), 24, fill="#12152d", outline="#8b53f5", width=2)
    draw.text((950, 450), "YOUR RANK", font=_font(23, True), anchor="mm", fill="#c5c9de")
    draw.text((950, 505), rank_text, font=_font(46, True), anchor="mm", fill="#bd8cff")

    # Game stats.
    stats_top = 590
    stats_bottom = 735
    _rounded(draw, (55, stats_top, 1145, stats_bottom), 24, fill="#10142b", outline="#2d57b7", width=2)
    draw.text((width // 2, stats_top + 18), "GAME STATS", font=_font(25, True), anchor="ma", fill="#63cfff")

    stats = [
        ("GAMES PLAYED", str(games), "🎮"),
        ("GAMES WON", str(wins), "🏆"),
        ("LOSSES", str(losses), "💥"),
        ("WIN RATE", f"{win_rate:.1f}%", "🎯"),
        ("LONGEST STREAK", str(longest), "🔥"),
    ]
    col_w = 1090 / len(stats)
    for idx, (label, value, icon) in enumerate(stats):
        cx = 55 + col_w * idx + col_w / 2
        if idx:
            x = int(55 + col_w * idx)
            draw.line((x, stats_top + 52, x, stats_bottom - 24), fill="#28345e", width=2)
        draw.text((cx, stats_top + 58), icon, font=_font(27), anchor="mm", fill="#ffffff")
        draw.text((cx, stats_top + 95), label, font=stat_label_font, anchor="mm", fill="#b9c2e0")
        draw.text((cx, stats_top + 130), value, font=stat_value_font, anchor="mm", fill="#f2f5ff")

    # Footer.
    _rounded(draw, (55, 760, 1145, 800), 16, fill="#0a0e20", outline="#43248f", width=2)
    draw.text((width // 2, 780), "✦ Keep playing and climb the rankings! 🚀", font=footer_font, anchor="mm", fill="#e4e8ff")

    output = BytesIO()
    output.name = "velocity_bingo_profile.png"
    # Fast PNG encoding: avoids the expensive optimizer while keeping the card sharp.
    image.save(output, format="PNG", optimize=False, compress_level=1)
    output.seek(0)
    return output


def build_profile_text(player: dict) -> str:
    username = player.get("username") or f"player_{player.get('telegram_id', '')}"
    username = "@" + str(username).lstrip("@")
    games = int(player.get("games_played", 0) or 0)
    wins = int(player.get("wins", 0) or 0)
    losses = int(player.get("losses", 0) or 0)
    coins = int(player.get("coins", 0) or 0)
    streak = int(player.get("current_streak", 0) or 0)
    longest = int(player.get("longest_streak", 0) or 0)
    win_rate = (wins / games * 100) if games else 0.0

    return (
        f"<blockquote><b>👤 YOUR PROFILE — {username}</b></blockquote>\n"
        f"💰 <b>Balance:</b> ${coins:,}\n"
        f"🎮 <b>Games:</b> {games}  |  🏆 <b>Wins:</b> {wins}\n"
        f"💥 <b>Losses:</b> {losses}  |  🎯 <b>Win Rate:</b> {win_rate:.1f}%\n"
        f"🔥 <b>Current Streak:</b> {streak}  |  ⭐ <b>Best Streak:</b> {longest}\n\n"
        "✨ Keep playing, winning and climbing the leaderboard!"
    )
