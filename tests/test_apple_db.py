import unittest
import plistlib
import json
import sqlite3
import tempfile
from pathlib import Path

try:
    # Prefer package import
    from chatlogtoeml.cli import apple_db as apple_db_cli
    from chatlogtoeml.parsers import apple_db as apple_db_module
    from chatlogtoeml.parsers import addressbook as addressbook_module
    from chatlogtoeml import conv_to_eml
except Exception:
    import apple_db as apple_db_cli
    import apple_db as apple_db_module
    import addressbook as addressbook_module
    import conv_to_eml


class TestAppleDBScaffold(unittest.TestCase):
    def test_converted_by_name_fallback(self):
        self.assertEqual(apple_db_cli._converted_by_name('-'), 'db_to_eml')
        self.assertEqual(apple_db_cli._converted_by_name(''), 'db_to_eml')
        self.assertEqual(apple_db_cli._converted_by_name('/usr/bin/python3'), 'db_to_eml')
        self.assertEqual(apple_db_cli._converted_by_name('/tmp/bin/db_to_eml'), 'db_to_eml')

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

    def test_addressbook_handle_keys_phone_and_email(self):
        keys_phone = addressbook_module.handle_keys("+1 (555) 555-0100")
        self.assertIn("15555550100", keys_phone)
        self.assertIn("5555550100", keys_phone)

        keys_email = addressbook_module.handle_keys("E:Owner@Example.COM")
        self.assertEqual(keys_email, {"owner@example.com"})

    def test_parse_file_enriches_owner_and_contact_names(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            sms_db = tdp / "sms.db"
            ab_db = tdp / "AddressBook.sqlitedb"

            sms_conn = sqlite3.connect(str(sms_db))
            sms_cur = sms_conn.cursor()
            sms_cur.executescript(
                """
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
                CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
                CREATE TABLE message (
                    ROWID INTEGER PRIMARY KEY,
                    guid TEXT,
                    text TEXT,
                    date INTEGER,
                    is_from_me INTEGER,
                    handle_id INTEGER,
                    service TEXT,
                    account TEXT
                );
                """
            )
            sms_cur.execute("INSERT INTO handle(ROWID, id) VALUES(1, '+15555550100')")
            sms_cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(1, 1)")
            sms_cur.execute(
                """
                INSERT INTO message(ROWID, guid, text, date, is_from_me, handle_id, service, account)
                VALUES(1, 'm-remote', 'hello from remote', 0, 0, 1, 'iMessage', 'e:owner@example.com')
                """
            )
            sms_cur.execute(
                """
                INSERT INTO message(ROWID, guid, text, date, is_from_me, handle_id, service, account)
                VALUES(2, 'm-local', 'hello from local', 60, 1, 0, 'iMessage', 'e:owner@example.com')
                """
            )
            sms_cur.execute("INSERT INTO chat_message_join(chat_id, message_id) VALUES(1, 1)")
            sms_cur.execute("INSERT INTO chat_message_join(chat_id, message_id) VALUES(1, 2)")
            sms_conn.commit()
            sms_conn.close()

            ab_conn = sqlite3.connect(str(ab_db))
            ab_cur = ab_conn.cursor()
            ab_cur.executescript(
                """
                CREATE TABLE ABPerson (
                    ROWID INTEGER PRIMARY KEY,
                    First TEXT,
                    Last TEXT,
                    Middle TEXT,
                    Organization TEXT,
                    Nickname TEXT,
                    DisplayName TEXT,
                    CompositeNameFallback TEXT
                );
                CREATE TABLE ABMultiValue (
                    record_id INTEGER,
                    property INTEGER,
                    value TEXT
                );
                CREATE TABLE ABStore (
                    ROWID INTEGER PRIMARY KEY,
                    Enabled INTEGER,
                    MeIdentifier INTEGER
                );
                """
            )
            ab_cur.execute(
                """
                INSERT INTO ABPerson(ROWID, First, Last, DisplayName, CompositeNameFallback)
                VALUES(1, 'Owner', 'Person', 'Owner Person', 'Owner Person')
                """
            )
            ab_cur.execute(
                """
                INSERT INTO ABPerson(ROWID, First, Last, DisplayName, CompositeNameFallback)
                VALUES(2, 'Remote', 'Friend', 'Remote Friend', 'Remote Friend')
                """
            )
            ab_cur.execute("INSERT INTO ABMultiValue(record_id, property, value) VALUES(1, 4, 'owner@example.com')")
            ab_cur.execute("INSERT INTO ABMultiValue(record_id, property, value) VALUES(2, 3, '(555) 555-0100')")
            ab_cur.execute("INSERT INTO ABStore(ROWID, Enabled, MeIdentifier) VALUES(1, 1, 1)")
            ab_conn.commit()
            ab_conn.close()

            convs = list(apple_db_module.parse_file(str(sms_db), addressbook_path=str(ab_db), min_messages=1))
            self.assertEqual(len(convs), 1)
            conv = convs[0]
            self.assertEqual(conv.localaccount, "owner@example.com")
            self.assertEqual(conv.get_realname_from_userid("owner@example.com"), "Owner Person")
            self.assertEqual(conv.get_realname_from_userid("+15555550100"), "Remote Friend")

            eml = conv_to_eml.mimefromconv(conv, no_background=False)
            self.assertIn("Owner Person", eml["From"])
            self.assertIn("Remote Friend", eml.as_string())


if __name__ == '__main__':
    unittest.main()
