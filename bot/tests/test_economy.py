import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import economy


class BetSettlementTests(unittest.TestCase):
    def test_settle_bet_result_updates_winner_and_loser(self):
        with patch("economy.db.update_user_stats", new_callable=AsyncMock) as update_user_stats, patch(
            "economy.db.log_game_result", new_callable=AsyncMock
        ) as log_game_result:
            asyncio.run(economy.settle_bet_result(101, 202, 50, 999))

            update_user_stats.assert_any_call(101, won=True, coins_delta=100)
            update_user_stats.assert_any_call(202, won=False, coins_delta=-50)
            log_game_result.assert_any_call(101, 999, won=True)
            log_game_result.assert_any_call(202, 999, won=False)


if __name__ == "__main__":
    unittest.main()
