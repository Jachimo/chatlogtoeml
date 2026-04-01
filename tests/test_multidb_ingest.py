import unittest
import datetime
import os
import sqlite3
import tempfile

from chatlogtoeml import multidb_ingest as mdi
from chatlogtoeml import conversation


class TestMultiDBIngestHelpers(unittest.TestCase):
    def test_merge_orig_paths_deduplicates(self):
        merged = mdi._merge_orig_paths('/a/b/c.jpg,/x/y/z.jpg', '/a/b/c.jpg')
        self.assertEqual(merged, '/a/b/c.jpg,/x/y/z.jpg')
        merged = mdi._merge_orig_paths(merged, '/n/m/q.jpg')
        self.assertEqual(merged, '/a/b/c.jpg,/x/y/z.jpg,/n/m/q.jpg')

    def test_choose_source_db_basename_majority(self):
        seg = [
            {'provenance': {'source_label': 'chat.db'}},
            {'provenance': {'source_label': 'sms.db'}},
            {'provenance': {'source_label': 'sms.db'}},
        ]
        self.assertEqual(mdi._choose_source_db_basename(seg), 'sms.db')

    def test_make_key_primary(self):
        rec = {'service': 'iMessage', 'guid': 'GUID123'}
        ktype, key = mdi._make_key(rec)
        self.assertEqual(ktype, 'primary')
        expected = mdi.ASCII_US.join(['imessage', 'GUID123'])
        self.assertEqual(key, expected)

    def test_make_key_fallback(self):
        ts = datetime.datetime(2020, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
        rec = {
            'service': 'iMessage',
            'chat_id': 'ChatA',
            'sender': 'Bob',
            'timestamp_utc': ts,
            'text_norm': '  Hello  world\n',
            'attachments': [],
        }
        ktype, key = mdi._make_key(rec)
        self.assertEqual(ktype, 'fallback')
        # normalized values should appear
        self.assertIn('chata', key)
        self.assertIn('Hello world', key)

    def test_attachment_identity_and_scoring(self):
        att = conversation.Attachment()
        att.name = 'photo.jpg'
        att.mimetype = 'image/jpeg'
        att.data = b'0123456789abcdef'
        typ, aid = mdi._attachment_identity(att)
        self.assertEqual(typ, 'hash')
        self.assertTrue(len(aid) >= 40 or len(aid) >= 10)

        rec = {
            'text_norm': 'Hi',
            'html_norm': '',
            'attachments': [{'payload_hash': aid, 'fingerprint': None, 'has_payload': True}],
            'guid': None,
            'metadata_score_inputs': {'reactions': True, 'realname': True},
        }
        h, a, m = mdi._score_candidate(rec)
        self.assertTrue(h > 1000)
        self.assertTrue(a >= 30)  # 10 for unique +20 for payload
        self.assertTrue(m >= 5)


class TestIngestSourcesAddressBook(unittest.TestCase):
    """Verify that addressbook_path is wired through ingest_sources and enriches
    participant display names on rebuilt Conversation objects."""

    def _make_sms_db(self, path: str, phone: str, text: str) -> None:
        """Create a minimal sms.db-style SQLite fixture."""
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)"
        )
        conn.execute("INSERT INTO handle VALUES (1, ?)", (phone,))
        conn.execute(
            """CREATE TABLE message (
               ROWID INTEGER PRIMARY KEY,
               guid TEXT,
               text TEXT,
               date INTEGER,
               is_from_me INTEGER,
               handle_id INTEGER,
               account TEXT,
               service TEXT
            )"""
        )
        # date in Apple epoch nanoseconds: 2001-01-21 02:08:09 UTC ~= 633830889
        conn.execute(
            "INSERT INTO message VALUES (1, 'GUID-001', ?, 633830889000000000, 0, 1, 'P:+19990000001', 'iMessage')",
            (text,)
        )
        conn.execute(
            "CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, guid TEXT)"
        )
        conn.execute("INSERT INTO chat VALUES (1, '1', 'SMS;-;+19990000001')")
        conn.execute(
            "CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        conn.execute(
            "CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)"
        )
        conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        conn.commit()
        conn.close()

    def _make_address_book(self, path: str, phone: str, name: str) -> None:
        """Create a minimal AddressBook.sqlitedb fixture."""
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE ABPerson (
               ROWID INTEGER PRIMARY KEY,
               First TEXT, Middle TEXT, Last TEXT,
               DisplayName TEXT, CompositeNameFallback TEXT,
               Organization TEXT, Nickname TEXT
            )"""
        )
        conn.execute("INSERT INTO ABPerson VALUES (1, ?, NULL, NULL, NULL, NULL, NULL, NULL)", (name,))
        # property 3 = phone
        conn.execute(
            "CREATE TABLE ABMultiValue (ROWID INTEGER PRIMARY KEY, record_id INTEGER, property INTEGER, value TEXT)"
        )
        conn.execute("INSERT INTO ABMultiValue VALUES (1, 1, 3, ?)", (phone,))
        conn.execute(
            "CREATE TABLE ABStore (ROWID INTEGER PRIMARY KEY, MeIdentifier INTEGER, Enabled INTEGER)"
        )
        conn.commit()
        conn.close()

    def test_addressbook_enriches_participants(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'sms.db')
            ab_path = os.path.join(tmp, 'AddressBook.sqlitedb')
            phone = '+13215362964'
            display_name = 'Test Contact'
            self._make_sms_db(db_path, phone, 'hello from the test')
            self._make_address_book(ab_path, phone, display_name)

            convs = list(mdi.ingest_sources(
                [db_path],
                local_handle='+19990000001',
                addressbook_path=ab_path,
                min_messages=1,
            ))

            self.assertGreater(len(convs), 0, 'Expected at least one conversation segment')
            # Find the remote participant (+13215362964) and check its realname
            all_participants = [p for conv in convs for p in conv.participants]
            remote = next(
                (p for p in all_participants if p.userid and '3215362964' in p.userid),
                None
            )
            self.assertIsNotNone(remote, f'Remote participant not found; participants: {[p.userid for p in all_participants]}')
            self.assertEqual(remote.realname, display_name,
                             f'Expected realname "{display_name}", got "{remote.realname}"')

    def test_no_addressbook_leaves_realname_empty(self):
        """Without an address book, realname should remain blank."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'sms.db')
            phone = '+13215362964'
            self._make_sms_db(db_path, phone, 'hello without AB')

            convs = list(mdi.ingest_sources(
                [db_path],
                local_handle='+19990000001',
                addressbook_path=None,
                min_messages=1,
            ))
            all_participants = [p for conv in convs for p in conv.participants]
            remote = next(
                (p for p in all_participants if p.userid and '3215362964' in p.userid),
                None
            )
            self.assertIsNotNone(remote)
            self.assertEqual(remote.realname, '')

    def test_source_db_basename_set_on_rebuilt_conv(self):
        """Rebuilt conversations must have source_db_basename set for correct fakedomain."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'sms.db')
            self._make_sms_db(db_path, '+13215362964', 'basename test')

            convs = list(mdi.ingest_sources([db_path], min_messages=1))
            for conv in convs:
                self.assertTrue(
                    conv.source_db_basename,
                    'source_db_basename should be non-empty for fakedomain derivation'
                )

    def test_local_account_set_on_rebuilt_conv(self):
        """local_handle must propagate to conv.localaccount so From: is correct."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'sms.db')
            local = '+19990000001'
            self._make_sms_db(db_path, '+13215362964', 'local account test')

            convs = list(mdi.ingest_sources([db_path], local_handle=local, min_messages=1))
            for conv in convs:
                local_parts = [p for p in conv.participants if p.position == 'local']
                self.assertTrue(
                    len(local_parts) > 0,
                    'At least one participant should be marked local'
                )

    def test_remote_participant_preserved_for_outgoing_only_segment(self):
        """Outgoing-only segments must still carry remote participants for name enrichment."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'sms.db')
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
            conn.execute("INSERT INTO handle VALUES (1, ?)", ('+13215362964',))
            conn.execute(
                """CREATE TABLE message (
                   ROWID INTEGER PRIMARY KEY,
                   guid TEXT,
                   text TEXT,
                   date INTEGER,
                   is_from_me INTEGER,
                   handle_id INTEGER,
                   account TEXT,
                   service TEXT
                )"""
            )
            conn.execute(
                "INSERT INTO message VALUES (1, 'GUID-OUT-1', 'hello remote', 633830889000000000, 1, 1, 'P:+19990000001', 'iMessage')"
            )
            conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, guid TEXT)")
            conn.execute("INSERT INTO chat VALUES (1, '1', 'SMS;-;+13215362964')")
            conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")
            conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
            conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")
            conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
            conn.commit()
            conn.close()

            convs = list(mdi.ingest_sources([db_path], local_handle='+19990000001', min_messages=1))
            self.assertGreater(len(convs), 0)
            participants = {p.userid for p in convs[0].participants}
            self.assertIn('+13215362964', participants)

    def test_text_is_not_whitespace_normalized_in_output_message(self):
        """Dedup keys should normalize text, but rebuilt messages must preserve source text."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'sms.db')
            original_text = 'Hello   world\nline  2'
            self._make_sms_db(db_path, '+13215362964', original_text)

            convs = list(mdi.ingest_sources([db_path], local_handle='+19990000001', min_messages=1))
            self.assertGreater(len(convs), 0)
            self.assertGreater(len(convs[0].messages), 0)
            self.assertEqual(convs[0].messages[0].text, original_text)

    def test_all_sources_fail_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = os.path.join(tmp, 'missing.db')
            with self.assertRaises(RuntimeError):
                list(mdi.ingest_sources([bad_path], min_messages=1))


if __name__ == '__main__':
    unittest.main()
