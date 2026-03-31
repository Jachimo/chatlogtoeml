import unittest
import datetime

from chatlogtoeml import multidb_ingest as mdi
from chatlogtoeml import conversation


class TestMultiDBIngestHelpers(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
