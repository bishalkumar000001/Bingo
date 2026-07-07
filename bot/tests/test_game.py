import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import game


class GameTurnPanelTests(unittest.TestCase):
    def test_update_group_turn_panel_uses_group_panel_message_id(self):
        room = {
            "id": "room-1",
            "chat_id": 999,
            "player1_id": 1,
            "player2_id": 2,
            "room_number": 7,
            "phase": "call",
            "group_panel_message_id": 222,
        }
        context = type("Ctx", (), {"bot": type("Bot", (), {"username": "testbot"})()})()
        with patch("game.db.update_room", new_callable=AsyncMock) as update_room, patch(
            "game._try_edit", new_callable=AsyncMock, return_value=True
        ) as try_edit, patch("game.build_group_turn_text", return_value="active"), patch(
            "game.build_group_turn_keyboard", return_value="keyboard"
        ):
            asyncio.run(game.update_group_turn_panel(context, room, 1, "Alice", "Bob"))

        self.assertEqual(try_edit.await_count, 1)
        self.assertEqual(try_edit.await_args_list[0].args[2], 222)
        update_room.assert_not_called()


if __name__ == "__main__":
    unittest.main()
