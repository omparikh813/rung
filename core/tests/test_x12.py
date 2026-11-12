from datetime import datetime, timezone

from django.test import override_settings
from django.urls import reverse

from core.models import Attempt, Claim, ClaimEvent, EventAction, FinalAction, Role
from core.skills import score_claim
from core.tests.base import SeededTestCase, make_user
from core.x12 import build_837p, clean, provider_name

WHEN = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)


def segments(text):
    return [line.rstrip("~").split("*") for line in text.strip().split("\n")]


class Build837Tests(SeededTestCase):
    def build(self, claim_id):
        claim = Claim.objects.get(claim_id=claim_id)
        return claim, segments(build_837p(claim, WHEN))

    def find(self, rows, name, first=None):
        return [row for row in rows if row[0] == name and (first is None or row[1] == first)]

    def test_envelope_and_control_numbers(self):
        claim, rows = self.build("CLM-1001")
        text = build_837p(claim, WHEN)
        isa = text.split("\n")[0]
        self.assertEqual(len(isa), 106)  # The ISA segment is always 106 characters.
        self.assertTrue(isa.startswith("ISA*00*          *00*          *ZZ*RUNGDEMO       *ZZ*CLEARINGHOUSE  *261116*0930*^*00501*"))
        self.assertTrue(isa.endswith("*0*T*:~"))
        self.assertEqual([row[0] for row in rows[:3]], ["ISA", "GS", "ST"])
        self.assertEqual([row[0] for row in rows[-3:]], ["SE", "GE", "IEA"])
        self.assertEqual(rows[1][8], "005010X222A1")
        self.assertEqual(rows[2], ["ST", "837", "0001", "005010X222A1"])
        self.assertEqual(rows[0][13], rows[-1][2])
        self.assertTrue(all(line.endswith("~") for line in text.strip().split("\n")))

    def test_se_counts_the_segments_from_st_to_se(self):
        for claim_id in ("CLM-1001", "CLM-1012", "CLM-1025"):
            _, rows = self.build(claim_id)
            start = next(i for i, row in enumerate(rows) if row[0] == "ST")
            end = next(i for i, row in enumerate(rows) if row[0] == "SE")
            self.assertEqual(int(rows[end][1]), end - start + 1, claim_id)

    def test_patient_payer_and_claim_segments(self):
        claim, rows = self.build("CLM-1001")
        self.assertEqual(self.find(rows, "NM1", "IL")[0], ["NM1", "IL", "1", "AVERY", "JORDAN", "", "", "", "MI", "SHP448120937"])
        self.assertEqual(self.find(rows, "DMG")[0], ["DMG", "D8", "19790314", "M"])
        self.assertEqual(self.find(rows, "NM1", "PR")[0][3], "SUMMIT HEALTH PPO")
        self.assertEqual(self.find(rows, "SBR")[0][-1], "CI")
        self.assertEqual(self.find(rows, "CLM")[0], ["CLM", "CLM-1001", "150", "", "", "11:B:1", "Y", "A", "Y", "Y"])
        self.assertEqual(self.find(rows, "HI")[0], ["HI", "ABK:I10", "ABF:E785"])
        self.assertEqual(self.find(rows, "NM1", "85")[0][-2:], ["XX", "1992047187"])
        self.assertEqual(self.find(rows, "NM1", "82")[0], ["NM1", "82", "1", "ORTIZ", "LENA", "", "", "", "XX", "1993012453"])
        self.assertEqual(self.find(rows, "SV1")[0], ["SV1", "HC:99213", "150", "UN", "1", "", "", "1:2"])
        self.assertEqual(self.find(rows, "DTP")[0], ["DTP", "472", "D8", "20261020"])

    def test_two_service_lines_modifiers_and_total(self):
        claim = Claim.objects.get(claim_id="CLM-1012")
        claim.modifiers_1 = "25"
        claim.save()
        rows = segments(build_837p(claim, WHEN))
        self.assertEqual([row[1] for row in self.find(rows, "LX")], ["1", "2"])
        self.assertEqual([row[1] for row in self.find(rows, "SV1")], ["HC:99213:25", "HC:20610:RT"])
        self.assertEqual(self.find(rows, "CLM")[0][2], "330")
        self.assertEqual(len(self.find(rows, "DTP")), 2)

    def test_medicare_medicaid_auth_referral_and_ndc(self):
        self.assertEqual(self.find(self.build("CLM-1002")[1], "SBR")[0][-1], "MB")
        _, rows = self.build("CLM-1025")
        self.assertEqual(self.find(rows, "SBR")[0][-1], "MC")
        self.assertEqual(self.find(rows, "LIN"), [])
        claim = Claim.objects.get(claim_id="CLM-1025")
        claim.ndc_code, claim.prior_auth_number, claim.referral_number = "12345678901", "SH4471932", "BVR20931"
        claim.save()
        rows = segments(build_837p(claim, WHEN))
        self.assertEqual(self.find(rows, "LIN")[0], ["LIN", "", "N4", "12345678901"])
        self.assertEqual(self.find(rows, "REF", "G1")[0][2], "SH4471932")
        self.assertEqual(self.find(rows, "REF", "9F")[0][2], "BVR20931")

    def test_missing_data_uses_the_placeholders_from_settings(self):
        text = build_837p(Claim.objects.get(claim_id="CLM-1001"), WHEN)
        for value in ("PLACEHOLDER MEDICAL GROUP", "123 PLACEHOLDER STREET", "REF*EI*000000000~", "PAYERID"):
            self.assertIn(value, text)
        with override_settings(RUNG_X12={**__import__("django.conf").conf.settings.RUNG_X12, "billing_provider_name": "Northside Clinic", "usage_indicator": "P"}):
            text = build_837p(Claim.objects.get(claim_id="CLM-1001"), WHEN)
        self.assertIn("NM1*85*2*NORTHSIDE CLINIC", text)
        self.assertIn("*0*P*:~", text)

    def test_delimiters_in_data_cannot_break_the_file(self):
        self.assertEqual(clean("O'Brien*~:^ jr"), "O'BRIEN     JR")
        claim = Claim.objects.get(claim_id="CLM-1001")
        claim.patient_last = "Av*ery~"
        rows = segments(build_837p(claim, WHEN))
        self.assertEqual(self.find(rows, "NM1", "IL")[0][3], "AV ERY")

    def test_provider_names(self):
        self.assertEqual(provider_name("Dr. Lena Ortiz (Family Medicine)"), ("Ortiz", "Lena"))
        self.assertEqual(provider_name("Marcus Chen"), ("Chen", "Marcus"))
        self.assertEqual(provider_name(""), ("", ""))

    def test_the_answer_key_is_never_in_the_file(self):
        for claim in Claim.objects.exclude(expected_issue=""):
            text = build_837p(claim, WHEN)
            self.assertNotIn(claim.expected_issue.upper()[:40], text)
            self.assertNotIn("EXPECTED", text)


class ExportViewTests(SeededTestCase):
    def setUp(self):
        super().setUp()
        self.claim = Claim.objects.get(claim_id="CLM-1001")
        self.url = reverse("claim_export", args=[self.claim.pk])

    def submit(self):
        ClaimEvent.objects.create(claim=self.claim, user=self.maria, action=EventAction.SUBMIT)
        score_claim(self.claim, self.maria, FinalAction.SUBMIT)

    def test_only_a_submitted_claim_can_be_exported(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.submit()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="CLM-1001_837P.txt"')
        self.assertTrue(response.content.decode().startswith("ISA*00*"))
        self.assertIn("CLM*CLM-1001*150", response.content.decode())

    def test_who_can_export(self):
        self.submit()
        self.client.force_login(make_user("other", Role.WORKER))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_passport_has_an_export_button_beside_each_submitted_claim(self):
        self.submit()
        escalated = Claim.objects.get(claim_id="CLM-1021")
        score_claim(escalated, self.maria, FinalAction.ESCALATE)
        self.assertEqual(Attempt.objects.count(), 2)
        response = self.client.get(reverse("passport"))
        self.assertContains(response, f'href="{self.url}"')
        self.assertContains(response, "Export 837", count=1)
        self.assertNotContains(response, reverse("claim_export", args=[escalated.pk]))
        self.assertContains(response, "Not submitted", count=1)

    def test_export_works_end_to_end_after_a_real_submit(self):
        from core.forms import ClaimForm

        data = {k: "" if v is None else str(v) for k, v in ClaimForm(instance=self.claim).initial.items()}
        self.client.post(reverse("claim", args=[self.claim.pk]), {**data, "action": "submit"})
        self.assertContains(self.client.get(reverse("passport")), f'href="{self.url}"')
        self.assertEqual(self.client.get(self.url).status_code, 200)
