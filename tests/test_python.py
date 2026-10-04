"""Python output regression checks, using a recorded real turn snapshot."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from terminal_stats import TerminalLog, format_turn

ROOT = Path(__file__).resolve().parent


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.event = json.loads((ROOT / "fixtures/turn.json").read_text(encoding="utf-8"))

    def test_duplicate_snapshot_is_saved_once_without_console_output(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
            log = TerminalLog(folder)
            log.accept(self.event)
            log.accept(self.event)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(log.text_path.read_text().count("次更新"), 1)
            self.assertEqual(len(log.json_path.read_text().splitlines()), 1)

    def test_title_identifies_initial_deal_and_other_players(self):
        self.event['trigger'] = 'ActionNewRound'
        self.assertIn('开局发牌', format_turn(self.event))
        self.event.update(trigger='ActionDiscardTile', actorSeat=2)
        text = format_turn(self.event)
        self.assertIn('座位2 出牌', text)
        self.assertNotIn('轮到你出牌', text)

    def test_heartbeat_is_silent(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
            log = TerminalLog(folder)
            log.accept({"session": "test", "serial": 1, "kind": "heartbeat"})
            self.assertEqual(out.getvalue(), "")
            self.assertFalse(log.json_path.exists())

    def test_riichi_marker_follows_other_players_names(self):
        for players in (3, 4):
            with self.subTest(players=players):
                self.event['state'].update(playerCount=players, selfSeat=0,
                                           riichi=[True, True, False, True])
                text = format_turn(self.event)
                self.assertIn('座位0 弃牌', text)
                self.assertIn('座位1（已立直） 弃牌', text)
                self.assertIn('座位2 弃牌', text)
                self.assertNotIn('座位0（已立直）', text)
                self.assertNotIn('座位2（已立直）', text)
                self.assertEqual(text.count('（已立直）'), players - 2)

    def test_unconfirmed_riichi_discard_does_not_mark_player(self):
        self.event['state']['riichi'] = [False] * 4
        self.event['state']['rivers'][1] = [{'tile': '1p', 'riichi': True}]
        text = format_turn(self.event)
        self.assertIn('1筒[立直]', text)
        self.assertNotIn('（已立直）', text)

    def test_incomplete_hand_does_not_count_stale_tiles(self):
        event = deepcopy(self.event)
        event["state"]["handComplete"] = False
        text = format_turn(event)
        event["state"]["hand"] += ["1m"] * 50
        self.assertEqual(text, format_turn(event))
        self.assertIn("本人完整手牌：尚未取得", text)
        self.assertIn("仅已观察部分", text)


if __name__ == "__main__":
    unittest.main()
