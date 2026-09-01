import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)
_background_tasks = set()


def create_background_task(coro, *, name: str):
    """Run a fire-and-forget coroutine without losing its exceptions."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _on_done(completed):
        _background_tasks.discard(completed)
        if completed.cancelled():
            return
        error = completed.exception()
        if error:
            logger.error(
                "Background task %s failed",
                completed.get_name(),
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(_on_done)
    return task


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
