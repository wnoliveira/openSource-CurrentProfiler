"""Measurement, serial framing and host-side firmware planning checks."""

import ctypes
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from current_scope.processing import scope_frame
from current_scope.protocol import (
    Data,
    Sample,
    Tracker,
    current_amp,
    decode,
    encode,
    planning,
)
from current_scope.worker import CSV_FIELDS, csv_row


class ProtocolTests(unittest.TestCase):
    def test_crc_reference_and_corruption(self):
        self.assertEqual(encode("123456789"), b"123456789*29B1\n")
        packet = Data(42, 1000020, -32000, 3)
        wire = encode("D,42,1000020,-32000,03")
        self.assertEqual(decode(wire), packet)
        with self.assertRaises(ValueError):
            decode(wire.replace(b"32000", b"32001"))

        invalid_frames = (
            encode("D,-1,1,0,00"),
            encode("D,0,1,32768,00"),
            b"noise\n",
        )
        for frame in invalid_frames:
            with self.subTest(frame=frame):
                with self.assertRaises(ValueError):
                    decode(frame)

    def test_rollover_loss_duplicate(self):
        tracker = Tracker()
        tracker.reset((1 << 32) - 100)
        first = tracker.accept(Data(0, (1 << 32) - 50, 1, 0))
        self.assertEqual(first.device_us, (1 << 32) - 50)

        after_rollover = tracker.accept(Data(2, 20, 1, 0))
        self.assertEqual(after_rollover.device_us, (1 << 32) + 20)
        self.assertEqual(tracker.lost, 1)
        self.assertIsNone(tracker.accept(Data(2, 20, 1, 0)))

        tracker.last_seq = (1 << 32) - 1
        self.assertIsNotNone(tracker.accept(Data(0, 30, 1, 0)))
        self.assertEqual(tracker.out_of_order, 1)

    def test_pga_is_not_multiplied_twice(self):
        self.assertAlmostEqual(current_amp(1000, 1), 0.01)
        self.assertAlmostEqual(current_amp(1002, 0.1, 2, 1.01), 0.101)
        with self.assertRaises(ValueError):
            current_amp(1, 0)

    def test_rate_average_budget(self):
        self.assertEqual(planning(1000), (1000, 1))
        self.assertEqual(planning(500), (2000, 2))
        self.assertEqual(planning(100), (10000, 16))
        self.assertEqual(planning(1), (1000000, 128))
        invalid_settings = ((1000, 2), (1000, 128), (100, 3), (0, 0), (1001, 0))
        for rate_hz, average in invalid_settings:
            with self.subTest(rate_hz=rate_hz, average=average):
                with self.assertRaises(ValueError):
                    planning(rate_hz, average)

    def test_csv_timestamp_has_microseconds_and_raw(self):
        metadata = dict(
            epoch_us=1000000,
            session=3,
            pga=2,
            averages=4,
            period_us=4000,
            zero_raw=2,
            gain=1,
        )
        anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row = csv_row(Sample(3, 1004500, 1002, 0), metadata, 1, anchor, 1)
        self.assertEqual(len(row), len(CSV_FIELDS))
        self.assertEqual(row[0], "2026-01-01T00:00:00.004500+00:00")
        self.assertEqual(float(row[7]), 0.01)
        self.assertEqual(row[11], 1)


class TriggerTests(unittest.TestCase):
    def test_rising_and_falling_center(self):
        times = np.arange(0, 3, 0.001)
        current = np.sin(times * 2 * np.pi * 5)
        for edge in ("Rising", "Falling"):
            with self.subTest(edge=edge):
                frame = scope_frame(times, current, 0.2, "Normal", 0.0, edge, 0.3)
                self.assertIsNotNone(frame)
                x, values, _, triggered = frame
                self.assertTrue(triggered)
                self.assertLessEqual(x[-1], 0.2)
                self.assertAlmostEqual(np.interp(0.06, x, values), 0, places=5)

    def test_no_trigger_and_gap(self):
        times = np.arange(100) * 0.001
        current = np.ones(100)
        self.assertIsNone(scope_frame(times, current, 0.02, "Normal", 2))
        self.assertFalse(scope_frame(times, current, 0.02, "Auto", 2)[3])

        current[49] = np.nan
        current[50:] = 3
        self.assertIsNone(scope_frame(times, current, 0.02, "Normal", 2))

    def test_trigger_behavior_is_independent_of_display_language(self):
        times = np.arange(0, 3, 0.001)
        current = np.sin(times * 2 * np.pi * 5)
        aliases = (
            ("Free", "Rising", "Livre", "Subida"),
            ("Normal", "Falling", "Normal", "Descida"),
            ("Single", "Rising", "\u00danico", "Subida"),
        )
        for mode, edge, old_mode, old_edge in aliases:
            with self.subTest(mode=mode, edge=edge):
                english = scope_frame(times, current, 0.2, mode, 0, edge)
                portuguese = scope_frame(times, current, 0.2, old_mode, 0, old_edge)
                self.assertIsNotNone(english)
                self.assertIsNotNone(portuguese)
                np.testing.assert_array_equal(english[0], portuguese[0])
                np.testing.assert_array_equal(english[1], portuguese[1])
                self.assertEqual(english[2:], portuguese[2:])


class FirmwareCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This is a host test, not an ESP32 build: the shared library must run
        # on this computer. An Xtensa cross-compiler cannot substitute for GCC.
        compiler = shutil.which("gcc")
        if compiler is None:
            raise unittest.SkipTest("Host GCC is unavailable; C/Python planning comparison skipped")

        cls.temp = tempfile.TemporaryDirectory()
        suffix = ".dll" if sys.platform == "win32" else ".so"
        library = Path(cls.temp.name) / ("scope_core" + suffix)
        command = [compiler, "-shared", "-Wall", "-Wextra", "-Werror"]
        if sys.platform != "win32":
            command.append("-fPIC")
        command.extend([str(ROOT / "firmware/main/scope_core.c"), "-o", str(library)])
        try:
            subprocess.run(command, check=True)
            cls.lib = ctypes.CDLL(str(library))
        except Exception:
            cls.temp.cleanup()
            raise

        class Plan(ctypes.Structure):
            _fields_ = [
                ("hz", ctypes.c_uint32),
                ("period", ctypes.c_uint32),
                ("averages", ctypes.c_uint16),
                ("adc", ctypes.c_uint16),
                ("typ", ctypes.c_uint32),
                ("maximum", ctypes.c_uint32),
            ]

        cls.Plan = Plan
        cls.lib.scope_plan.restype = ctypes.c_bool
        cls.lib.scope_plan.argtypes = [
            ctypes.c_uint32, ctypes.c_uint16, ctypes.POINTER(Plan)
        ]
        cls.lib.scope_config.restype = ctypes.c_uint16
        cls.lib.scope_config.argtypes = [ctypes.c_uint8, ctypes.c_uint16]
        cls.lib.scope_crc.restype = ctypes.c_uint16
        cls.lib.scope_crc.argtypes = [ctypes.c_char_p, ctypes.c_size_t]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_1000_rates_against_python(self):
        for rate_hz in range(1, 1001):
            with self.subTest(rate_hz=rate_hz):
                plan = self.Plan()
                self.assertTrue(self.lib.scope_plan(rate_hz, 0, ctypes.byref(plan)))
                self.assertEqual((plan.period, plan.averages), planning(rate_hz))
                self.assertLessEqual(plan.maximum + 350, plan.period)
                for pga in range(4):
                    config = self.lib.scope_config(pga, plan.adc)
                    self.assertEqual(config & 7, 1)
                    self.assertEqual((config >> 11) & 3, pga)
                    self.assertEqual((config >> 3) & 15, plan.adc)

        self.assertEqual(self.lib.scope_crc(b"123456789", 9), 0x29B1)


if __name__ == "__main__":
    unittest.main()
