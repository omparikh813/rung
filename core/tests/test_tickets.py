from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Role, Ticket, TicketMessage, TicketStatus
from core.tests.base import SeededTestCase, make_user

URL = reverse("tickets")


class TicketTestCase(SeededTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.steven = User.objects.get(username="steven")
        self.seeded = Ticket.objects.get(subject="More time for new hire reviews")

    def detail(self, ticket):
        return reverse("ticket_detail", args=[ticket.pk])


class SpecialistTicketTests(TicketTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.dan)

    def test_specialist_opens_a_ticket_to_the_admin(self):
        response = self.client.post(URL, {"subject": "Need access", "body": "Can I get the Case Library export?"}, follow=True)
        ticket = Ticket.objects.get(subject="Need access")
        self.assertRedirects(response, self.detail(ticket))
        self.assertContains(response, "Ticket sent to your admin.")
        self.assertEqual((ticket.specialist, ticket.opened_by, ticket.organization, ticket.from_admin), (self.dan, self.dan, self.ags, False))
        self.assertEqual(ticket.messages.get().body, "Can I get the Case Library export?")

    def test_every_field_is_needed(self):
        response = self.client.post(URL, {"subject": "", "body": "x"})
        self.assertContains(response, "Fill in every field before sending.")
        self.assertEqual(Ticket.objects.count(), 1)

    def test_specialist_sees_only_their_own_conversations(self):
        other = make_user("erin", Role.SPECIALIST, self.ags)
        Ticket.objects.create(organization=self.ags, specialist=other, opened_by=other, subject="Erin's ticket")
        subjects = [row["ticket"].subject for row in self.client.get(URL).context["rows"]]
        self.assertEqual(subjects, ["More time for new hire reviews"])
        self.assertEqual(self.client.get(self.detail(Ticket.objects.get(subject="Erin's ticket"))).status_code, 404)

    def test_specialist_cannot_close_a_conversation(self):
        self.assertEqual(self.client.post(reverse("ticket_status", args=[self.seeded.pk])).status_code, 403)

    def test_workers_have_no_messages(self):
        self.client.force_login(self.maria)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.get(self.detail(self.seeded)).status_code, 403)
        self.assertNotIn("Messages", [item["label"] for item in self.client.get(reverse("queue")).context["nav_items"]])


class AdminTicketTests(TicketTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.om)

    def test_admin_sees_the_seeded_ticket_waiting_on_them(self):
        response = self.client.get(URL)
        rows = response.context["rows"]
        self.assertEqual([row["ticket"].subject for row in rows], ["More time for new hire reviews"])
        self.assertTrue(rows[0]["waiting"])
        nav = {item["label"]: item.get("count") for item in response.context["nav_items"]}
        self.assertEqual(nav["Messages"], 1)

    def test_admin_replies_and_the_specialist_sees_it(self):
        self.client.post(self.detail(self.seeded), {"body": "Yes, Tuesdays and Thursdays."})
        self.assertEqual(self.seeded.messages.count(), 2)
        self.assertEqual(self.client.get(URL).context["nav_items"][1]["count"], 0)
        self.client.force_login(self.dan)
        page = self.client.get(self.detail(self.seeded))
        self.assertContains(page, "Yes, Tuesdays and Thursdays.")
        self.assertTrue(self.client.get(URL).context["rows"][0]["waiting"])

    def test_admin_messages_a_specialist(self):
        response = self.client.post(URL, {"specialist": self.dan.pk, "subject": "Coaching plan", "body": "Please pair with Kevin this week."}, follow=True)
        ticket = Ticket.objects.get(subject="Coaching plan")
        self.assertContains(response, "Message sent to James.")
        self.assertEqual((ticket.specialist, ticket.opened_by, ticket.from_admin), (self.dan, self.om, True))
        self.client.force_login(self.dan)
        self.assertIn("Coaching plan", [row["ticket"].subject for row in self.client.get(URL).context["rows"]])

    def test_admin_can_only_message_their_own_active_specialists(self):
        for target in (self.maria, self.steven):
            self.client.post(URL, {"specialist": target.pk, "subject": "x", "body": "y"})
        self.assertEqual(Ticket.objects.count(), 1)

    def test_admin_closes_and_reopens(self):
        response = self.client.post(reverse("ticket_status", args=[self.seeded.pk]), follow=True)
        self.assertContains(response, "Conversation closed.")
        self.seeded.refresh_from_db()
        self.assertEqual(self.seeded.status, TicketStatus.CLOSED)
        self.client.force_login(self.dan)
        self.assertEqual(self.client.post(self.detail(self.seeded), {"body": "one more thing"}).status_code, 403)
        self.client.force_login(self.om)
        self.client.post(reverse("ticket_status", args=[self.seeded.pk]))
        self.seeded.refresh_from_db()
        self.assertEqual(self.seeded.status, TicketStatus.OPEN)

    def test_another_organizations_admin_cannot_see_it(self):
        self.client.force_login(self.steven)
        self.assertEqual(self.client.get(URL).context["rows"], [])
        self.assertEqual(self.client.get(self.detail(self.seeded)).status_code, 404)
        self.assertEqual(self.client.post(reverse("ticket_status", args=[self.seeded.pk])).status_code, 404)
        self.assertContains(self.client.get(URL), "no active specialists")

    def test_empty_reply_is_rejected(self):
        response = self.client.post(self.detail(self.seeded), {"body": "  "}, follow=True)
        self.assertContains(response, "Write a reply before sending.")
        self.assertEqual(TicketMessage.objects.filter(ticket=self.seeded).count(), 1)
