"""Offline protocol and failure-path tests. These do not test physical hardware."""
import io
import json
import struct
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import barracuda as b


# Public HID descriptor, OpenRazer issue #2704. Binary protocol data.
DESCRIPTOR = bytes.fromhex("""
06 13 FF 09 01 A1 01 15 00 26 FF 00 85 06 09 00
75 08 95 3D 91 02 85 07 09 00 75 08 95 3D 81 02
C0 05 0C 09 01 A1 01 85 0C 15 00 25 01 09 E9 09
EA 09 E2 09 CD 09 B5 09 B6 75 01 95 06 81 02 09
00 95 02 81 02 C0 05 0B 09 05 A1 01 15 00 25 01
75 01 85 05 09 20 95 01 81 22 09 2F 95 01 81 06
09 24 09 21 09 97 09 2A 09 50 95 05 81 06 09 07
05 09 09 01 75 01 95 01 81 02 05 08 85 05 09 17
09 09 09 18 09 20 09 21 09 2A 95 06 91 22 95 02
91 01 C0 06 14 FF 09 01 A1 01 15 00 26 FF 00 85
02 09 00 75 08 95 08 B2 02 01 85 02 09 00 75 08
95 3F 91 02 85 02 09 00 75 08 95 3F 81 02 C0 05
59 09 01 A1 01 85 31 09 02 A1 02 09 03 15 00 27
FF FF 00 00 75 10 95 01 B1 03 09 04 09 05 09 06
09 07 09 08 15 00 27 FF FF FF 7F 75 20 95 05 B1
03 C0 85 32 09 20 A1 02 09 21 15 00 27 FF FF 00
00 75 10 95 01 B1 02 C0 85 33 09 22 A1 02 09 21
15 00 27 FF FF 00 00 75 10 95 01 B1 02 09 23 09
24 09 25 09 27 09 26 15 00 27 FF FF FF 7F 75 20
95 05 B1 02 09 28 09 29 09 2A 09 2B 09 2C 09 2D
15 00 26 FF 00 75 08 95 06 B1 02 C0 85 34 09 50
A1 02 09 03 09 55 15 00 25 08 75 08 95 02 B1 02
09 21 15 00 27 FF FF 00 00 75 10 95 08 B1 02 09
51 09 52 09 53 09 54 09 51 09 52 09 53 09 54 09
51 09 52 09 53 09 54 09 51 09 52 09 53 09 54 09
51 09 52 09 53 09 54 09 51 09 52 09 53 09 54 09
51 09 52 09 53 09 54 09 51 09 52 09 53 09 54 15
00 26 FF 00 75 08 95 20 B1 02 C0 85 35 09 60 A1
02 09 55 15 00 25 08 75 08 95 01 B1 02 09 61 09
62 15 00 27 FF FF 00 00 75 10 95 02 B1 02 09 51
09 52 09 53 09 54 15 00 26 FF 00 75 08 95 04 B1
02 C0 85 36 09 70 A1 02 09 71 15 00 25 01 75 08
95 01 B1 02 C0 C0
""")


def incoming(prop, payload, event=False, include_id=False):
    # Synthetic replies follow the reported shape, not a real USBPcap fixture.
    data = bytearray(64)
    data[:3] = bytes((2, 10 if event else 2, 0x60))
    data[6] = 4 + len(payload)
    data[8:13] = bytes((0x80, 0x80, prop, 2 if event else 1, len(payload)))
    data[13:13 + len(payload)] = payload
    crc = 0
    for byte in data[0 if include_id else 1:62]:
        crc ^= byte
    data[62] = crc
    return bytes(data)


class OfflineTests(unittest.TestCase):
    def test_real_descriptor_layout(self):
        self.assertEqual(len(DESCRIPTOR), 518)
        self.assertEqual(b.capabilities(DESCRIPTOR), {"vendor": True, "rgb": True})
        report = b.parse_descriptor(DESCRIPTOR)
        self.assertEqual(b.report_length(report[("feature", 0x34)], 0x34), 51)
        self.assertEqual(b.report_length(report[("feature", 0x31)], 0x31), 23)
        self.assertEqual(b.report_length(report[("output", 2)], 2), 64)

    def test_wrong_page_disables_vendor(self):
        altered = DESCRIPTOR.replace(bytes.fromhex("06 14 ff"), bytes.fromhex("06 15 ff"))
        self.assertFalse(b.capabilities(altered)["vendor"])

    def test_rgb_same_size_wrong_channel_order_is_rejected(self):
        altered = DESCRIPTOR.replace(bytes.fromhex("09 51 09 52"), bytes.fromhex("09 52 09 51"))
        self.assertFalse(b.capabilities(altered)["rgb"])

    def test_malformed_descriptor_rejected(self):
        for bad in (b"\x27\x00", b"\xb4", b"\xfe\x00\x00"):
            with self.assertRaises(b.DeviceError):
                b.parse_descriptor(bad)

    def test_battery_get_exact_prefix_checksum(self):
        data = b.request_report(0x21)
        self.assertEqual(len(data), 64)
        self.assertEqual(data[:13], bytes.fromhex("02 00 60 00 00 00 04 00 00 80 21 00 00"))
        self.assertEqual(data[13:62], bytes(49))
        self.assertEqual(data[62:], bytes.fromhex("c7 00"))

    def test_preset_set_exact_header_checksum(self):
        data = b.request_report(0x13, b"\x07")
        self.assertEqual(data[:14], bytes.fromhex("02 00 60 00 00 00 05 00 00 80 93 00 01 07"))
        self.assertEqual(data[62:], bytes.fromhex("72 00"))

    def test_invalid_writes_rejected(self):
        for prop, payload in ((0x21, b"\x63"), (0x18, b"\x02"), (0x19, b"\x10"),
                              (0x2C, b"\x05"), (0x55, b"\x01"), (0x13, b"\x00"),
                              (0x15, bytes((7,)) * 10), (0x15, bytes(9))):
            with self.subTest(prop=prop), self.assertRaises(b.DeviceError):
                b.request_report(prop, payload)

    def test_custom_eq_signed_encoding(self):
        gains = [-6, -3, -2, -1, 0, 1, 2, 3, 4, 6]
        report = b.request_report(0x15, struct.pack("10b", *gains))
        self.assertEqual(report[6], 14)
        self.assertEqual(report[12], 10)
        self.assertEqual(report[13:23], bytes((250, 253, 254, 255, 0, 1, 2, 3, 4, 6)))

    def test_event_and_reply_are_distinct(self):
        event = b.parse_message(incoming(0x21, b"\x63", event=True))
        reply = b.parse_message(incoming(0x21, b"\x63"))
        self.assertEqual((event.kind, reply.kind), ("event", "reply"))
        self.assertEqual(reply.payload, b"\x63")

    def test_bad_checksum_and_out_of_range_battery_rejected(self):
        valid = incoming(0x21, b"\x63")
        self.assertIsNotNone(b.parse_message(valid))
        corrupt = bytearray(valid)
        corrupt[13] ^= 4
        self.assertIsNone(b.parse_message(corrupt))
        self.assertIsNone(b.parse_message(incoming(0x21, b"\xff")))
        self.assertIsNone(b.parse_message(valid[:-1]))
        self.assertIsNone(b.parse_message(b""))

    def test_reply_checksum_coverage_is_observable(self):
        msg = b.parse_message(incoming(0x19, b"\x0f", include_id=True))
        self.assertEqual(msg.checksum_style, "with_report_id")

    def test_unexpected_reply_length_or_status_rejected(self):
        for offset, value in ((6, 6), (11, 0), (12, 2), (63, 1), (8, 0)):
            bad = bytearray(incoming(0x21, b"\x32"))
            bad[offset] = value
            bad[62] = b.checksum(bad[1:62])
            self.assertIsNone(b.parse_message(bad))

    def test_zero_padded_lamp_layout(self):
        colors = [(i, i + 10, i + 20) for i in range(6)]
        data = b.lamp_report(colors, 50)
        self.assertEqual(len(data), 51)
        self.assertEqual(data[:3], bytes.fromhex("34 06 01"))
        self.assertEqual(struct.unpack_from("<8H", data, 3), (0, 1, 2, 3, 4, 5, 0, 0))
        for i, color in enumerate(colors):
            self.assertEqual(data[19 + i * 4:23 + i * 4], bytes((*color, 128)))
        self.assertEqual(data[43:], bytes(8))

    def test_rgb_invalid_inputs_rejected_before_feature_writes(self):
        c = object.__new__(b.Controller)
        c._feature = Mock()
        with self.assertRaises(b.DeviceError):
            c.rgb([(255, 0, 0)], 50)
        c._feature.assert_not_called()
        for colors, level in (([(0, 0, 0)] * 6, 101), ([(256, 0, 0)] * 6, 50)):
            with self.assertRaises(b.DeviceError):
                b.lamp_report(colors, level)

    def test_no_set_if_get_fails(self):
        c = object.__new__(b.Controller)
        c.get = Mock(side_effect=b.DeviceError("No reply"))
        c._output = Mock()
        with self.assertRaises(b.DeviceError):
            c.set(0x18, b"\x01")
        c._output.assert_not_called()

    def test_no_set_when_value_unchanged(self):
        c = object.__new__(b.Controller)
        c.get = Mock(return_value=b"\x01")
        c._output = Mock()
        self.assertEqual(c.set(0x18, b"\x01")["result"], "already_set")
        c._output.assert_not_called()

    @patch("barracuda.time.sleep")
    def test_mismatched_readback_never_reports_success_or_retries_set(self, _sleep):
        c = object.__new__(b.Controller)
        c.get = Mock(return_value=b"\x00")
        c._output = Mock()
        with self.assertRaisesRegex(b.DeviceError, "not confirmed"):
            c.set(0x18, b"\x01")
        self.assertEqual(c._output.call_count, 1)
        self.assertEqual(c.get.call_count, 3)

    @patch("barracuda.time.sleep")
    def test_missing_readback_is_unknown_outcome(self, _sleep):
        c = object.__new__(b.Controller)
        c.get = Mock(side_effect=[b"\x00", b.DeviceError("Disconnected")])
        c._output = Mock()
        with self.assertRaisesRegex(b.DeviceError, "UNKNOWN"):
            c.set(0x18, b"\x01")
        self.assertEqual(c._output.call_count, 1)

    @patch("barracuda.time.sleep")
    def test_matching_readback_reports_success(self, _sleep):
        c = object.__new__(b.Controller)
        c.get = Mock(side_effect=[b"\x00", b"\x01"])
        c._output = Mock()
        self.assertEqual(c.set(0x18, b"\x01")["result"], "readback_matched")

    def test_custom_curve_preflight_and_partial_change_report(self):
        c = object.__new__(b.Controller)
        c.get = Mock(return_value=bytes(10))
        c.set = Mock(side_effect=[{"result": "readback_matched"}, b.DeviceError("No readback")])
        with self.assertRaisesRegex(b.DeviceError, "Custom preset was selected"):
            c.set_curve([0] * 10)
        self.assertEqual(c.set.call_args_list[0].args, (0x13, b"\xff"))

    def test_get_ignores_unsolicited_event_and_other_property(self):
        c = object.__new__(b.Controller)
        c.caps, c.passive, c.link = {"vendor": True}, False, None
        c.reply_checksums = set()
        c._drain, c._output = Mock(), Mock()
        c._read = Mock(side_effect=[incoming(0x21, b"\x42", event=True),
                                   incoming(0x19, b"\x03"), incoming(0x21, b"\x43")])
        self.assertEqual(c.get(0x21), b"\x43")
        self.assertEqual(c._read.call_count, 3)

    def test_diagnose_never_opens_usb(self):
        output = io.StringIO()
        with patch.object(b, "discover", return_value=[]), patch.object(b.os, "open") as opened:
            with redirect_stdout(output):
                self.assertEqual(b.main(["diagnose"]), 0)
            opened.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["devices"], [])

    def test_rgb_attributes_validate_count_kind(self):
        c = object.__new__(b.Controller)
        c._feature = Mock(return_value=struct.pack("<BHIIIII", 0x31, 6, 10000, 10000, 10000, 11, 20000))
        self.assertEqual(c.rgb_attributes()["lamps"], 6)
        c._feature.return_value = struct.pack("<BHIIIII", 0x31, 12, 10000, 10000, 10000, 11, 20000)
        with self.assertRaises(b.DeviceError):
            c.rgb_attributes()

    def test_passive_connection_cannot_send_query_or_setting(self):
        c = object.__new__(b.Controller)
        c.caps, c.passive = {"vendor": True}, True
        c._drain = Mock()
        with self.assertRaises(b.DeviceError):
            c.get(0x21)
        c._drain.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
