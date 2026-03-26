import unittest
import datetime

from chatlogtoeml import conversation, conv_to_eml

class TestConvToEmlEdgeCases(unittest.TestCase):
    def test_userid_case_insensitive(self):
        conv = conversation.Conversation()
        conv.add_participant('Me@Example.COM')
        conv.add_participant('friend')
        conv.set_local_account('me@example.com')
        # both should be recognized as local if case-insensitive
        self.assertTrue(conv.userid_islocal('Me@Example.COM'))
        self.assertTrue(conv.userid_islocal('me@example.com'))

    def test_attachment_contentid_uniqueness(self):
        a1 = conversation.Attachment()
        a1.name = 'file1.txt'
        a1.mimetype = 'text/plain'
        a1.data = b''
        a1.gen_contentid()
        a2 = conversation.Attachment()
        a2.name = 'file2.txt'
        a2.mimetype = 'text/plain'
        a2.data = b''
        a2.gen_contentid()
        self.assertNotEqual(a1.contentid, a2.contentid)

    def test_no_background_css_removed(self):
        conv = conversation.Conversation()
        conv.add_participant('me')
        conv.add_participant('other')
        conv.set_local_account('me')
        m = conversation.Message('message')
        m.msgfrom = 'me'
        m.text = 'hello'
        m.html = '<div style="background-color: #ff0000;">hello</div>'
        m.date = datetime.datetime(2021,1,1,0,0,0, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        # produce EML with no_background True
        eml = conv_to_eml.mimefromconv(conv, no_background=True)
        # extract html part
        alt = eml.get_payload()[0]
        html_part = alt.get_payload()[1]
        payload_bytes = html_part.get_payload(decode=True)
        if isinstance(payload_bytes, bytes):
            html = payload_bytes.decode('utf-8', errors='ignore')
        else:
            html = str(payload_bytes)
        self.assertNotIn('background-color', html.lower())

    def test_reaction_html_preserved(self):
        conv = conversation.Conversation()
        conv.add_participant('me')
        conv.add_participant('bob')
        conv.set_local_account('me')
        m = conversation.Message('message')
        m.guid = 'g1'
        m.msgfrom = 'bob'
        m.text = 'hello'
        m.html = '<p>hello</p><div class="reactions"><span class="reaction">👍×2</span></div>'
        m.date = datetime.datetime(2021,1,1,0,0,0, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        eml = conv_to_eml.mimefromconv(conv)
        alt = eml.get_payload()[0]
        html_part = alt.get_payload()[1]
        payload_bytes = html_part.get_payload(decode=True)
        if isinstance(payload_bytes, bytes):
            html = payload_bytes.decode('utf-8', errors='ignore')
        else:
            html = str(payload_bytes)
        self.assertIn('reaction', html)
        self.assertIn('👍', html)

if __name__ == '__main__':
    unittest.main()
