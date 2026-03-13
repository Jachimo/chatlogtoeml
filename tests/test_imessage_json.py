import unittest
import tempfile
import os
import json

import imessage_json


class TestReactions(unittest.TestCase):
    def test_grouped_reaction_html(self):
        msg = {'guid':'m1','text':'Hello','date':'2021-01-01T00:00:00Z','is_from_me':False,'sender':'alice'}
        r1 = {'associated_message_guid':'m1','reaction_type':'like','actor':'bob','date':'2021-01-01T00:01:00Z'}
        r2 = {'associated_message_guid':'m1','reaction_type':'like','actor':'carol','date':'2021-01-01T00:02:00Z'}
        conv = imessage_json.build_conversation_from_segment([msg, r1, r2], 'chatA', 'sample.ndjson', None)
        m = next((mm for mm in conv.messages if getattr(mm, 'guid', '') == 'm1'), None)
        self.assertIsNotNone(m)
        html = getattr(m, 'html', '') or ''
        text = getattr(m, 'text', '') or ''
        # expect either html reactions or textual fallback
        self.assertTrue('reaction' in html or '👍' in html or '👍' in text)

    def test_embed_attachments(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'file.txt')
            with open(p, 'wb') as f:
                f.write(b'hello')
            msg = {'guid':'m2','text':'See file','date':'2021-01-01T01:00:00Z','is_from_me':False,'sender':'alice','attachments':[{'filename':'file.txt','path':p,'mime_type':'text/plain'}]}
            conv = imessage_json.build_conversation_from_segment([msg], 'chatA','sample.ndjson', None, embed_attachments=True)
            m = conv.getoldestmessage()
            self.assertTrue(m.attachments)
            self.assertEqual(m.attachments[0].data, b'hello')


class TestStreaming(unittest.TestCase):
    def test_stream_parse(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td,'test.ndjson')
            msgs = [
                {'chat_identifier':'c1','guid':'g1','text':'a','date':'2021-01-01T00:00:00Z','is_from_me':False,'sender':'a'},
                {'chat_identifier':'c1','guid':'g2','text':'b','date':'2021-01-01T00:01:00Z','is_from_me':False,'sender':'a'},
                {'chat_identifier':'c2','guid':'g3','text':'c','date':'2021-01-02T00:00:00Z','is_from_me':False,'sender':'b'},
                {'chat_identifier':'c2','guid':'g4','text':'d','date':'2021-01-02T00:01:00Z','is_from_me':False,'sender':'b'},
            ]
            with open(p,'w') as fh:
                for o in msgs:
                    fh.write(json.dumps(o) + '\n')
            convs = list(imessage_json.parse_file(p, local_handle=None, min_messages=1, stream=True))
            # Expect at least two conversations (one per chat id)
            self.assertGreaterEqual(len(convs), 2)


if __name__ == '__main__':
    unittest.main()
