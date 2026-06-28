from typing import Optional


def mention(user_id: int, name: str) -> str:
    safe = name.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


def display_name(user) -> str:
    if hasattr(user, "username") and user.username:
        return f"@{user.username}"
    return user.first_name or str(user.id)


def display_name_from_db(row: dict) -> str:
    if row.get("username"):
        return f"@{row['username']}"
    return row.get("first_name") or str(row["telegram_id"])


def format_called_numbers(called: list) -> str:
    if not called:
        return "None"
    return " • ".join(str(n) for n in called)


def medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
