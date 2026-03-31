import unittest
import datetime
import json

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
        self.assertEqual(eml['Subject'], 'iMessage with Remote Friend on Tue, Feb 12 2013')

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
        self.assertEqual(eml['Subject'], 'iMessage with Local User on Tue, Feb 12 2013')

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
        self.assertIn('Subject: iMessage with Remote User on Fri, Feb  1 2013', raw)
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
        self.assertEqual(eml['Subject'], 'iMessage with 15555550999 on Wed, Apr  3 2013')

    def test_subject_keeps_semantic_identifier_without_hash(self):
        conv = conversation.Conversation()
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = 'family-group@example.com'
        conv.source_db_basename = 'chat.db'
        conv.add_participant('local.user@example.test')
        conv.add_participant('friend@example.com')
        conv.set_local_account('local.user@example.test')
        conv.add_realname_to_userid('local.user@example.test', 'Local User')
        conv.add_realname_to_userid('friend@example.com', 'Remote Friend')

        m = conversation.Message('message')
        m.msgfrom = 'friend@example.com'
        m.text = 'group ping'
        m.date = datetime.datetime(2014, 5, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        conv.startdate = m.date

        eml = conv_to_eml.mimefromconv(conv)
        self.assertEqual(eml['Subject'], 'iMessage with Remote Friend (family-group@example.com) on Sun, May  4 2014')

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


class TestMessageIndex(unittest.TestCase):
    """Tests for _make_message_index_part and its integration into mimefromconv."""

    def _make_conv(self, guids, chat_identifier='chat-42',
                   startdate=None, enddate=None):
        """Helper: build a minimal Conversation with the given list of GUIDs."""
        conv = conversation.Conversation()
        conv.filenameuserid = chat_identifier
        conv.add_participant('me')
        conv.add_participant('other')
        conv.set_local_account('me')
        if startdate:
            conv.startdate = startdate
        if enddate:
            conv.enddate = enddate
        for guid in guids:
            m = conversation.Message('message')
            m.guid = guid
            m.msgfrom = 'me'
            m.text = 'hi'
            m.date = datetime.datetime(2021, 6, 1, 12, 0, 0,
                                       tzinfo=datetime.timezone.utc)
            conv.add_message(m)
        return conv

    # ------------------------------------------------------------------
    # _make_message_index_part unit tests
    # ------------------------------------------------------------------

    def test_returns_none_when_no_guids(self):
        conv = self._make_conv([])
        # add a guid-less message manually
        m = conversation.Message('message')
        m.msgfrom = 'me'
        m.text = 'no guid here'
        m.date = datetime.datetime(2021, 6, 1, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        part, digest = conv_to_eml._make_message_index_part(conv)
        self.assertIsNone(part)
        self.assertIsNone(digest)

    def test_returns_none_when_guid_is_empty_string(self):
        conv = self._make_conv([''])  # empty-string guid should be filtered out
        part, digest = conv_to_eml._make_message_index_part(conv)
        self.assertIsNone(part)
        self.assertIsNone(digest)

    def test_returns_none_when_guid_is_whitespace(self):
        conv = self._make_conv(['   '])
        part, digest = conv_to_eml._make_message_index_part(conv)
        self.assertIsNone(part)
        self.assertIsNone(digest)

    def test_non_string_guid_is_normalized_to_string(self):
        conv = self._make_conv([12345])
        part, digest = conv_to_eml._make_message_index_part(conv)
        self.assertIsNotNone(part)
        self.assertIsNotNone(digest)
        data = json.loads(part.get_payload(decode=True))
        self.assertEqual(data['message_guids'], ['12345'])

    def test_returns_part_and_digest_when_guids_present(self):
        conv = self._make_conv(['AAAA-1111', 'BBBB-2222'])
        part, digest = conv_to_eml._make_message_index_part(conv)
        self.assertIsNotNone(part)
        self.assertIsNotNone(digest)
        self.assertEqual(len(digest), 64)  # SHA-256 produces a 64-char hex string

    def test_json_structure_is_correct(self):
        start = datetime.datetime(2021, 6, 1, 10, 0, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2021, 6, 1, 11, 0, tzinfo=datetime.timezone.utc)
        conv = self._make_conv(
            ['guid-c', 'guid-a', 'guid-b'],
            chat_identifier='chat-99',
            startdate=start,
            enddate=end,
        )
        part, digest = conv_to_eml._make_message_index_part(conv)
        raw = part.get_payload(decode=True)
        data = json.loads(raw)

        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(data['chat_identifier'], 'chat-99')
        self.assertEqual(data['guid_count'], 3)
        self.assertEqual(data['message_count'], 3)
        self.assertEqual(data['guid_sha256'], digest)
        self.assertEqual(data['segment_start'], start.isoformat())
        self.assertEqual(data['segment_end'], end.isoformat())
        # message_guids must preserve chronological insertion order
        self.assertEqual(data['message_guids'], ['guid-c', 'guid-a', 'guid-b'])
        # sorted order used for the digest must differ from insertion order here
        self.assertEqual(sorted(['guid-c', 'guid-a', 'guid-b']),
                         ['guid-a', 'guid-b', 'guid-c'])

    def test_sha256_is_order_independent(self):
        """Same set of GUIDs in different insertion orders must hash identically."""
        _, digest_abc = conv_to_eml._make_message_index_part(
            self._make_conv(['guid-a', 'guid-b', 'guid-c']))
        _, digest_cba = conv_to_eml._make_message_index_part(
            self._make_conv(['guid-c', 'guid-b', 'guid-a']))
        _, digest_bac = conv_to_eml._make_message_index_part(
            self._make_conv(['guid-b', 'guid-a', 'guid-c']))
        self.assertEqual(digest_abc, digest_cba)
        self.assertEqual(digest_abc, digest_bac)

    def test_sha256_differs_for_different_guid_sets(self):
        _, d1 = conv_to_eml._make_message_index_part(
            self._make_conv(['guid-a', 'guid-b']))
        _, d2 = conv_to_eml._make_message_index_part(
            self._make_conv(['guid-a', 'guid-x']))
        self.assertNotEqual(d1, d2)

    def test_content_type_and_disposition(self):
        conv = self._make_conv(['some-guid'])
        part, _ = conv_to_eml._make_message_index_part(conv)
        ct = part.get_content_type()
        self.assertEqual(ct, 'application/x-chatlogtoeml-index')
        disp = part.get_param('filename', header='content-disposition')
        self.assertEqual(disp, 'chatlogtoeml-index.json')

    # ------------------------------------------------------------------
    # Integration tests: mimefromconv output contains index
    # ------------------------------------------------------------------

    def test_eml_includes_index_header_when_guids_present(self):
        conv = self._make_conv(['test-guid-0001', 'test-guid-0002'])
        eml = conv_to_eml.mimefromconv(conv)
        self.assertIn('X-Message-Index-SHA256', eml)

    def test_eml_index_header_matches_attachment_digest(self):
        conv = self._make_conv(['g1', 'g2', 'g3'])
        eml = conv_to_eml.mimefromconv(conv)
        header_digest = eml['X-Message-Index-SHA256']
        # Find the chatlogtoeml-index attachment in the MIME tree
        index_data = None
        for part in eml.walk():
            if part.get_content_type() == 'application/x-chatlogtoeml-index':
                index_data = json.loads(part.get_payload(decode=True))
                break
        self.assertIsNotNone(index_data, 'chatlogtoeml-index attachment not found')
        self.assertEqual(header_digest, index_data['guid_sha256'])

    def test_eml_no_index_header_when_no_guids(self):
        conv = conversation.Conversation()
        conv.add_participant('me')
        conv.add_participant('other')
        conv.set_local_account('me')
        m = conversation.Message('message')
        # intentionally no guid
        m.msgfrom = 'me'
        m.text = 'legacy message without guid'
        m.date = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)
        conv.add_message(m)
        eml = conv_to_eml.mimefromconv(conv)
        self.assertNotIn('X-Message-Index-SHA256', eml)
        # also verify no index attachment parts
        for part in eml.walk():
            self.assertNotEqual(part.get_content_type(),
                                'application/x-chatlogtoeml-index')


if __name__ == '__main__':
    unittest.main()
