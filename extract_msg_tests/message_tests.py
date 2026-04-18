__all__ = [
    'MessageTests',
]


import unittest
from email.message import EmailMessage

from .constants import TEST_FILE_DIR
from extract_msg import openMsg
from extract_msg.msg_classes import Message


class MessageTests(unittest.TestCase):
    def testMultiTo(self):
        """
        Tests parsing a message with multiple To and CC recipients.
        """
        with openMsg(TEST_FILE_DIR / 'multi-to.msg') as msg:
            self.assertIsInstance(msg, Message)

            self.assertTrue(msg.subject.startswith('Test: multiple To recipients'))
            self.assertEqual(msg.sender, 'Bob Sender <bob@example.com>')
            self.assertTrue((msg.body or '').startswith('Test email body.'))

            # Expect at least two To recipients (type 1) and at least one CC (type 2).
            to_recipients = [r for r in msg.recipients if r.type == 1]
            cc_recipients = [r for r in msg.recipients if r.type == 2]

            self.assertGreaterEqual(len(to_recipients), 2)
            self.assertGreaterEqual(len(cc_recipients), 1)

            to_emails = [r.email.strip('\x00') for r in to_recipients]
            self.assertIn('alice@example.com', to_emails)
            self.assertIn('carol@example.com', to_emails)

            cc_emails = [r.email.strip('\x00') for r in cc_recipients]
            self.assertIn('dave@example.com', cc_emails)

    def testMultiToAsEmailMessage(self):
        """
        Tests that a message with multiple To recipients converts to EML without error,
        and that duplicate To headers are merged into a single comma-separated value.
        """
        with openMsg(TEST_FILE_DIR / 'multi-to.msg') as msg:
            em = msg.asEmailMessage()

            self.assertIsInstance(em, EmailMessage)
            # EmailMessage must have exactly one TO field (duplicates merged).
            self.assertEqual(sum(1 for k in em.keys() if k == 'TO'), 1)
            to_header = em['TO']
            self.assertIn('alice@example.com', to_header)
            self.assertIn('carol@example.com', to_header)
            self.assertEqual(em['CC'], 'Dave Jones <dave@example.com>')
            self.assertEqual(em['From'], 'Bob Sender <bob@example.com>')
