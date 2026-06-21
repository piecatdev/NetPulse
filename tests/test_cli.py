from __future__ import annotations

import contextlib
import io
import unittest

from netpulse.cli import build_parser


class CliParserTests(unittest.TestCase):
    def test_rejects_non_positive_scan_options(self) -> None:
        parser = build_parser()

        for option in ("--interval", "--timeout", "--concurrency"):
            with self.subTest(option=option):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(["192.168.1.0/24", option, "0"])

    def test_rejects_negative_retention_days(self) -> None:
        parser = build_parser()

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["192.168.1.0/24", "--retention-days", "-1"])

    def test_accepts_positive_scan_options(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "192.168.1.0/24",
                "--interval",
                "2.5",
                "--timeout",
                "0.2",
                "--concurrency",
                "8",
            ]
        )

        self.assertEqual(args.interval, 2.5)
        self.assertEqual(args.timeout, 0.2)
        self.assertEqual(args.concurrency, 8)

    def test_accepts_zero_retention_days(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["192.168.1.0/24", "--retention-days", "0"])

        self.assertEqual(args.retention_days, 0)


if __name__ == "__main__":
    unittest.main()
