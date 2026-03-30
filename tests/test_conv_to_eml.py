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

    def test_html_includes_stylesheet_classes(self):
        conv = conversation.Conversation()
        conv.add_participant('me')
        conv.add_participant('other')
        conv.set_local_account('me')
        m = conversation.Message('message')
        m.msgfrom = 'other'
        m.text = 'styled hello'
        m.date = datetime.datetime(2021, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        conv.add_message(m)

        eml = conv_to_eml.mimefromconv(conv)
        alt = eml.get_payload()[0]
        html_part = alt.get_payload()[1]
        payload_bytes = html_part.get_payload(decode=True)
        if isinstance(payload_bytes, bytes):
            html = payload_bytes.decode('utf-8', errors='ignore')
        else:
            html = str(payload_bytes)

        self.assertIn('<style', html.lower())
        self.assertIn('.localname', html)
        self.assertIn('.remotename', html)
        self.assertIn('.timestamp', html)

    def test_imessage_subject_includes_name_and_chat_id(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = '12'
        conv.source_db_basename = 'sms.db'
        conv.add_participant('local.user@example.test')
        conv.add_participant('+15555550100')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')
        conv.add_realname_to_userid('+15555550100', 'Remote Friend')

        m = conversation.Message('message')
        m.msgfrom = 'local.user@example.test'
        m.text = 'hello'
        m.date = datetime.datetime(2013, 2, 12, 6, 6, 54, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        self.assertEqual(eml['Subject'], 'iMessage with Remote Friend #12 on Tue, Feb 12 2013')

    def test_imessage_self_chat_subject_uses_local_name_and_chat_id(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = '12'
        conv.source_db_basename = 'sms.db'
        conv.add_participant('local.user@example.test')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')

        m = conversation.Message('message')
        m.msgfrom = 'local.user@example.test'
        m.text = 'self note'
        m.date = datetime.datetime(2013, 2, 12, 6, 6, 54, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        self.assertEqual(eml['Subject'], 'iMessage with Local User #12 on Tue, Feb 12 2013')

    def test_headers_are_ascii_sanitized(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = '2'
        conv.source_db_basename = 'sms.db'
        conv.add_participant('local.user@example.test')
        conv.add_participant('+15555550123')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')
        conv.add_realname_to_userid('+15555550123', 'Remote User 💩')

        m = conversation.Message('message')
        m.msgfrom = '+15555550123'
        m.text = 'hello'
        m.date = datetime.datetime(2013, 2, 1, 1, 50, 56, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        raw = eml.as_string()
        self.assertIn('Subject: iMessage with Remote User #2 on Fri, Feb  1 2013', raw)
        self.assertIn('To: Remote User <15555550123@sms.imessage.invalid>', raw)
        self.assertNotIn('=?utf-8?', raw.lower())

    def test_subject_fallback_uses_sanitized_to_handle(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = '24'
        conv.source_db_basename = 'sms.db'
        conv.add_participant('local.user@example.test')
        conv.add_participant('+15555550999')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')

        m = conversation.Message('message')
        m.msgfrom = '+15555550999'
        m.text = 'ping'
        m.date = datetime.datetime(2013, 4, 3, 3, 7, 44, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        self.assertEqual(eml['Subject'], 'iMessage with 15555550999 #24 on Wed, Apr  3 2013')

    def test_tel_handle_to_header_uses_rfc_safe_pseudo_address(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = 'tel:+15555550977'
        conv.source_db_basename = 'sms.db'
        conv.add_participant('local.user@example.test')
        conv.add_participant('tel:+15555550977')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')
        conv.add_realname_to_userid('tel:+15555550977', 'Remote Contact')

        m = conversation.Message('message')
        m.msgfrom = 'tel:+15555550977'
        m.text = 'hi'
        m.date = datetime.datetime(2015, 1, 24, 17, 25, 8, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        raw = eml.as_string()
        self.assertIn('To: Remote Contact <15555550977@sms.imessage.invalid>', raw)
        self.assertNotIn('<tel>', raw)
        self.assertNotIn('tel:+15555550977@sms.imessage.invalid', raw)

    def test_unknown_handle_display_name_uses_stripped_phone(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = '12'
        conv.source_db_basename = 'sms.db'
        conv.add_participant('local.user@example.test')
        conv.add_participant('+17033463295')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')

        m = conversation.Message('message')
        m.msgfrom = '+17033463295'
        m.text = 'hi'
        m.date = datetime.datetime(2015, 1, 24, 17, 25, 8, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        raw = eml.as_string()
        self.assertIn('To: 17033463295 <17033463295@sms.imessage.invalid>', raw)

if __name__ == '__main__':
    unittest.main()
