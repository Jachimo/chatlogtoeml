import unittest
import plistlib
import json
from pathlib import Path

try:
    # Prefer package import
    from chatlogtoeml.parsers import apple_db as apple_db_module
except Exception:
    import apple_db as apple_db_module


class TestAppleDBScaffold(unittest.TestCase):
    def test_parse_file_exists(self):
        self.assertTrue(callable(getattr(apple_db_module, 'parse_file', None)))

    def test_apple_ts_conversion(self):
        # Apple timestamp 0 should convert to year 2001 (2001-01-01)
        dt = apple_db_module.apple_ts_to_dt(0)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2001)

    def test_decode_streamtyped_legacy(self):
        # Build a synthetic streamtyped payload with START/END markers and a 1-char prefix.
        raw = b"streamtypedjunk" + b"\x01\x2b" + b"\x06Hello from attributedBody" + b"\x86\x84" + b"tail"
        txt = apple_db_module._decode_streamtyped_legacy(raw)
        self.assertEqual(txt, "Hello from attributedBody")

    def test_decode_payload_blob_nskeyed_plist(self):
        # Minimal NSKeyedArchiver-ish object graph with root -> NSString
        uid = plistlib.UID  # type: ignore[attr-defined]
        payload = {
            "$archiver": "NSKeyedArchiver",
            "$version": 100000,
            "$objects": [
                "$null",
                {"NS.string": uid(2), "$class": uid(3)},
                "Hello from payload_data",
                {"$classname": "NSString", "$classes": ["NSString", "NSObject"]},
            ],
            "$top": {"root": uid(1)},
        }
        blob = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
        txt = apple_db_module._decode_payload_blob(blob)
        self.assertEqual(txt, "Hello from payload_data")

    def test_decode_message_text_fallback_order(self):
        # text column should take precedence when present
        out = apple_db_module._decode_message_text(
            "from_text_col",
            b"\x01\x2b\x06from_attr\x86\x84",
            None,
        )
        self.assertEqual(out, "from_text_col")

        # if text is empty, attributedBody should be used
        out2 = apple_db_module._decode_message_text(
            "",
            b"\x01\x2b\x06from_attr\x86\x84",
            None,
        )
        self.assertEqual(out2, "from_attr")

        # if both text and attributedBody absent/unreadable, payload_data should be used
        uid = plistlib.UID  # type: ignore[attr-defined]
        payload = {
            "$archiver": "NSKeyedArchiver",
            "$version": 100000,
            "$objects": [
                "$null",
                {"NS.string": uid(2), "$class": uid(3)},
                "from_payload",
                {"$classname": "NSString", "$classes": ["NSString", "NSObject"]},
            ],
            "$top": {"root": uid(1)},
        }
        blob = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
        out3 = apple_db_module._decode_message_text(None, b"", blob)
        self.assertEqual(out3, "from_payload")

    def test_blob_case_fixture_decode_matrix(self):
        # Fixture generator writes expected text for each GUID into JSON.
        root = Path(__file__).resolve().parents[1]
        expected_ios_path = root / "samples" / "blob_cases" / "ios" / "sms_blob_cases_expected.json"
        expected_mac_path = root / "samples" / "blob_cases" / "macos" / "chat_blob_cases_expected.json"
        ios_db = root / "samples" / "blob_cases" / "ios" / "sms_blob_cases.db"
        mac_db = root / "samples" / "blob_cases" / "macos" / "chat_blob_cases.db"

        # Skip if fixtures not generated yet (tests can still run in minimal environments).
        if not (expected_ios_path.exists() and expected_mac_path.exists() and ios_db.exists() and mac_db.exists()):
            self.skipTest("blob case fixtures not generated; run tools/generate_blob_case_fixtures.py")

        expected = {}
        expected.update(json.loads(expected_ios_path.read_text(encoding="utf-8")))
        expected.update(json.loads(expected_mac_path.read_text(encoding="utf-8")))

        got = {}
        for db in (ios_db, mac_db):
            for conv in apple_db_module.parse_file(str(db), min_messages=1):
                for msg in conv.messages:
                    if msg.guid in expected:
                        got[msg.guid] = msg.text or ""

        missing = sorted(set(expected.keys()) - set(got.keys()))
        self.assertEqual(missing, [], f"Missing decoded messages for GUIDs: {missing}")
        for guid, want in expected.items():
            self.assertEqual(got.get(guid, ""), want, f"Mismatch for {guid}")


if __name__ == '__main__':
    unittest.main()
