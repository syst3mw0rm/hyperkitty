# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import datetime
from email.message import Message
from email import message_from_file

from django.utils import timezone
from django.db import IntegrityError

from hyperkitty.models import MailingList, Email, Thread, Attachment
from hyperkitty.lib.incoming import add_to_list
from hyperkitty.lib.utils import get_message_id_hash
from hyperkitty.tests.utils import TestCase, get_test_file


class TestFetch(TestCase):

    def setUp(self):
        self.mlist = MailingList.objects.create(
            name="example-list",
            display_name="name 1",
            subject_prefix="[prefix 1]")
        self.m_hash = self.add_fetch_data()

    def add_fetch_data(self):
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Subject"] = "Fake Subject"
        msg["Message-ID"] = "<dummy>"
        msg["Date"] = "Fri, 02 Nov 2012 16:07:54"
        msg.set_payload("Fake Message")
        return add_to_list("example-list", msg)

    def test_get_message_by_id_from_list(self):
        """Get a Message in a List by Message-ID """
        try:
            m = Email.objects.get(mailinglist=self.mlist, message_id="dummy")
        except Email.DoesNotExist:
            self.fail("No email found")
        self.assertEqual(m.sender_id, "dummy@example.com")
        self.assertEqual(m.sender.address, "dummy@example.com")

    def test_get_thread(self):
        """Get a Thread in a List by Thread-ID """
        # Test assumes message_id_hash == thread_id
        try:
            m = Email.objects.get(mailinglist=self.mlist,
                                  message_id_hash=self.m_hash)
        except Email.DoesNotExist:
            self.fail("No email found")
        self.assertEqual(m.thread.thread_id, self.m_hash)


class TestAddToList(TestCase):

    def test_no_message_id(self):
        msg = Message()
        self.assertRaises(ValueError, add_to_list,
                          "example-list", msg)

    def test_no_date(self):
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        #now = datetime.datetime.utcnow()
        now = timezone.now()
        try:
            add_to_list("example-list", msg)
        except IntegrityError as e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        self.assertTrue(stored_msg.date >= now)

    def test_date_naive(self):
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Message-ID"] = "<dummy>"
        msg["Date"] = "Fri, 02 Nov 2012 16:07:54"
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except IntegrityError as e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        expected = datetime.datetime(2012, 11, 2, 16, 7, 54,
                                     tzinfo=timezone.utc)
        self.assertEqual(stored_msg.date, expected)
        self.assertEqual(stored_msg.timezone, 0)

    def test_date_aware(self):
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Message-ID"] = "<dummy>"
        msg["Date"] = "Fri, 02 Nov 2012 16:07:54 +0100"
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except IntegrityError, e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        expected = datetime.datetime(2012, 11, 2, 15, 7, 54,
                                     tzinfo=timezone.utc)
        self.assertEqual(stored_msg.date, expected)
        self.assertEqual(stored_msg.timezone, 60)

    def test_duplicate(self):
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        add_to_list("example-list", msg)
        mlist = MailingList.objects.get(name="example-list")
        self.assertEqual(mlist.emails.count(), 1)
        self.assertTrue(mlist.emails.filter(message_id="dummy").exists())
        add_to_list("example-list", msg)
        self.assertEqual(mlist.emails.count(), 1)

    def test_non_ascii_email_address(self):
        """Non-ascii email addresses should raise a ValueError exception"""
        msg = Message()
        msg["From"] = b"dummy-non-ascii-\xc3\xa9@example.com"
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except ValueError, e:
            self.assertEqual(e.__class__.__name__, "ValueError")
        else:
            self.fail("No ValueError was raised")
        self.assertEqual(0,
            MailingList.objects.get(name="example-list").emails.count())

    def test_duplicate_nonascii(self):
        msg = Message()
        msg["From"] = b"dummy-ascii@example.com"
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        add_to_list("example-list", msg)
        mlist = MailingList.objects.get(name="example-list")
        self.assertEqual(mlist.emails.count(), 1)
        self.assertTrue(mlist.emails.filter(message_id="dummy").exists())
        msg.replace_header("From", b"dummy-non-ascii\xc3\xa9@example.com")
        try:
            add_to_list("example-list", msg)
        except UnicodeDecodeError, e:
            self.fail("Died on a non-ascii header message: %s" % unicode(e))
        self.assertEqual(mlist.emails.count(), 1)

    def test_attachment_insert_order(self):
        """Attachments must not be inserted in the DB before the email"""
        with open(get_test_file("attachment-1.txt")) as email_file:
            msg = message_from_file(email_file)
        try:
            add_to_list("example-list", msg)
        except IntegrityError, e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        self.assertEqual(Attachment.objects.count(), 1)

    def test_thread_neighbors(self):
        # Create 3 threads
        msg_t1_1 = Message()
        msg_t1_1["From"] = "dummy@example.com"
        msg_t1_1["Message-ID"] = "<id1_1>"
        msg_t1_1.set_payload("Dummy message")
        add_to_list("example-list", msg_t1_1)
        msg_t2_1 = Message()
        msg_t2_1["From"] = "dummy@example.com"
        msg_t2_1["Message-ID"] = "<id2_1>"
        msg_t2_1.set_payload("Dummy message")
        add_to_list("example-list", msg_t2_1)
        msg_t3_1 = Message()
        msg_t3_1["From"] = "dummy@example.com"
        msg_t3_1["Message-ID"] = "<id3_1>"
        msg_t3_1.set_payload("Dummy message")
        add_to_list("example-list", msg_t3_1)
        # Check the neighbors
        def check_neighbors(thread, expected_prev, expected_next):
            thread_id = get_message_id_hash("<id%s_1>" % thread)
            thread = Thread.objects.get(thread_id=thread_id)
            prev_th = next_th = None
            # convert to something I can compare
            if thread.prev_thread:
                prev_th = thread.prev_thread.thread_id
            if thread.next_thread:
                next_th = thread.next_thread.thread_id
            expected_prev = expected_prev and \
                    get_message_id_hash("<id%s_1>" % expected_prev)
            expected_next = expected_next and \
                    get_message_id_hash("<id%s_1>" % expected_next)
            # compare
            self.assertEqual(prev_th, expected_prev)
            self.assertEqual(next_th, expected_next)
        # Order should be: 1, 2, 3
        check_neighbors(1, None, 2)
        check_neighbors(2, 1, 3)
        check_neighbors(3, 2, None)
        # now add a new message in thread 1, which becomes the most recently
        # active
        msg_t1_2 = Message()
        msg_t1_2["From"] = "dummy@example.com"
        msg_t1_2["Message-ID"] = "<id1_2>"
        msg_t1_2["In-Reply-To"] = "<id1_1>"
        msg_t1_2.set_payload("Dummy message")
        add_to_list("example-list", msg_t1_2)
        # Order should be: 2, 3, 1
        check_neighbors(2, None, 3)
        check_neighbors(3, 2, 1)
        check_neighbors(1, 3, None)

    def test_long_message_id(self):
        # Some message-ids are more than 255 chars long
        # Check with assert here because SQLite will not enforce the limit
        # (http://www.sqlite.org/faq.html#q9)
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Message-ID"] = "X" * 260
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except IntegrityError, e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        self.assertTrue(len(stored_msg.message_id) <= 255,
                "Very long message-id headers are not truncated")

    def test_long_message_id_reply(self):
        # Some message-ids are more than 255 chars long, we'll truncate them
        # but check that references are preserved
        msg1 = Message()
        msg1["From"] = "dummy@example.com"
        msg1["Message-ID"] = "<" + ("X" * 260) + ">"
        msg1.set_payload("Dummy message")
        msg2 = Message()
        msg2["From"] = "dummy@example.com"
        msg2["Message-ID"] = "<Y>"
        msg2["References"] = "<" + ("X" * 260) + ">"
        msg2.set_payload("Dummy message")
        add_to_list("example-list", msg1)
        add_to_list("example-list", msg2)
        stored_msg1 = Email.objects.get(message_id="X" * 254)
        stored_msg2 = Email.objects.get(message_id="Y")
        self.assertEqual(stored_msg2.in_reply_to, "X" * 254)
        self.assertEqual(stored_msg2.parent_id, stored_msg1.id)
        self.assertEqual(stored_msg2.thread_order, 1)
        self.assertEqual(stored_msg2.thread_depth, 1)
        self.assertEqual(Thread.objects.count(), 1)
        thread = Thread.objects.all()[0]
        self.assertEqual(thread.emails.count(), 2)

    def test_top_participants(self):
        expected = [
            ("name3", "email3", 3),
            ("name2", "email2", 2),
            ("name1", "email1", 1),
            ]
        for name, email, count in expected:
            for num in range(count):
                msg = Message()
                msg["From"] = "%s <%s>" % (name, email)
                msg["Message-ID"] = "<%s_%s>" % (name, num)
                msg.set_payload("Dummy message")
                add_to_list("example-list", msg)
        #now = timezone.now()
        #yesterday = now - datetime.timedelta(days=1)
        mlist = MailingList.objects.get(name="example-list")
        result = [(p.name, p.address, p.count) for p in
                   mlist.top_posters ]
        self.assertEqual(expected, result)

    def test_get_sender_name(self):
        msg = Message()
        msg["From"] = "Sender Name <dummy@example.com>"
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        add_to_list("example-list", msg)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        self.assertEqual(stored_msg.sender.name, "Sender Name")

    def test_no_sender_address(self):
        msg = Message()
        msg["From"] = "Sender Name <>"
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except IntegrityError as e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        self.assertEqual(stored_msg.sender.name, "Sender Name")
        self.assertEqual(stored_msg.sender.address, "sendername@example.com")

    def test_no_sender_name_or_address(self):
        msg = Message()
        msg["From"] = ""
        msg["Message-ID"] = "<dummy>"
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except IntegrityError as e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        self.assertEqual(stored_msg.sender.name, "")
        self.assertEqual(stored_msg.sender.address, "unknown@example.com")

    def test_long_subject(self):
        msg = Message()
        msg["From"] = "dummy@example.com"
        msg["Message-ID"] = "<dummy>"
        msg["Subject"] = "x" * 600
        msg.set_payload("Dummy message")
        try:
            add_to_list("example-list", msg)
        except IntegrityError as e:
            self.fail(e)
        self.assertEqual(Email.objects.count(), 1)
        stored_msg = Email.objects.all()[0]
        self.assertEqual(len(stored_msg.subject), 512)



#class TestStormStoreWithSearch(unittest.TestCase):
#
#    def setUp(self):
#        self.tmpdir = mkdtemp(prefix="kittystore-testing-")
#        settings = SettingsModule()
#        settings.KITTYSTORE_SEARCH_INDEX = self.tmpdir
#        search_index = _get_search_index(settings)
#        self.store = get_sa_store(settings, search_index=search_index, auto_create=True)
#        search_index.upgrade(self.store)
#        kittystore.utils.MM_CLIENT = Mock()
#
#    def tearDown(self):
#        self.store.close()
#        rmtree(self.tmpdir)
#        kittystore.utils.MM_CLIENT = None
#
#    def test_private_list(self):
#        # emails on private lists must not be found by a search on all lists
#        ml = FakeList("example-list")
#        ml.archive_policy = "private"
#        kittystore.utils.MM_CLIENT.get_list.side_effect = lambda n: ml
#        msg = Message()
#        msg["From"] = "dummy@example.com"
#        msg["Message-ID"] = "<dummy>"
#        msg.set_payload("Dummy message")
#        self.store.add_to_list("example-list", msg)
#        result = self.store.search("dummy")
#        self.assertEqual(result["total"], 0)
