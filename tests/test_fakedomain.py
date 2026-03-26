import unittest
import datetime

from chatlogtoeml import conversation, conv_to_eml


class TestFakeDomain(unittest.TestCase):
    def make_conv(self, basename):
        conv = conversation.Conversation()
        conv.origfilename = f'/path/to/{basename}'
        conv.imclient = 'iMessage'
        conv.service = 'iMessage'
        conv.filenameuserid = 'user'
        conv.add_participant('user')
        conv.add_participant('me')
        conv.set_local_account('me')
        m = conversation.Message('message')
        m.guid = 'g'
        m.msgfrom = 'user'
        m.date = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)
        m.text = 'hi'
        conv.add_message(m)
        return conv

    def test_sms_basename(self):
        conv = self.make_conv('sms.db')
        msg = conv_to_eml.mimefromconv(conv)
        self.assertIn('@sms.imessage.invalid', msg.get('Message-ID', ''))

    def test_chat_basename(self):
        conv = self.make_conv('chat.db')
        msg = conv_to_eml.mimefromconv(conv)
        self.assertIn('@chat.imessage.invalid', msg.get('Message-ID', ''))


if __name__ == '__main__':
    unittest.main()
