from collections import deque
from unittest import TestCase
from unittest.mock import patch

import can2yd


class FakeBus:
    def __init__(self):
        self.fail = True
        self.sent = []

    def send(self, message, timeout):
        if self.fail:
            raise OSError(105, "No buffer space available")
        self.sent.append((message, timeout))


class Can2YdTests(TestCase):
    def test_parse_short_and_raw_transmit_lines(self):
        self.assertEqual(
            can2yd.parse_tx_line("1DEFFF73 E3 00"),
            (0x1DEFFF73, b"\xe3\x00"),
        )
        self.assertEqual(
            can2yd.parse_tx_line("12:00:00.000 T 1DEFFF73 E3 00"),
            (0x1DEFFF73, b"\xe3\x00"),
        )

    def test_reject_invalid_can_frames(self):
        self.assertEqual(can2yd.parse_tx_line("20000000 00"), (None, None))
        self.assertEqual(
            can2yd.parse_tx_line("1DEFFF73 00 01 02 03 04 05 06 07 08"),
            (None, None),
        )

    def test_transmit_queue_preserves_frame_after_backpressure(self):
        queue = deque([(0x1DEFFF73, b"\xe3\x00")])
        bus = FakeBus()

        with patch.object(can2yd, "make_can_message", side_effect=lambda *args: args):
            sent, error = can2yd.flush_can_tx_queue(bus, queue)
            self.assertEqual(sent, [])
            self.assertIsNotNone(error)
            self.assertEqual(len(queue), 1)

            bus.fail = False
            sent, error = can2yd.flush_can_tx_queue(bus, queue)

        self.assertIsNone(error)
        self.assertEqual(sent, [(0x1DEFFF73, b"\xe3\x00")])
        self.assertEqual(queue, deque())
        self.assertEqual(bus.sent, [((0x1DEFFF73, b"\xe3\x00"), 0)])
