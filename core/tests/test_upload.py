import csv
import io

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.claims import ANSWER_KEY_FIELDS, CSV_COLUMNS
from core.models import Attempt, Claim, FinalAction, WorkStatus
from core.skills import score_claim
from core.tests.base import SEEDED_CLAIMS, SeededTestCase

GOOD = {
    "claim_id": "CLM-3001", "patient_first": "Pat", "patient_last": "Lee", "payer_name": "Summit Health PPO",
    "date_of_service": "2026-11-01", "cpt_1": "99213", "icd10_primary": "I10",
}  # fmt: skip


def csv_file(rows, columns=None, name="claims.csv"):
    columns = columns or list(rows[0])
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return SimpleUploadedFile(name, out.getvalue().encode(), content_type="text/csv")


class UploadTestCase(SeededTestCase):
    url = reverse("upload")

    def preview(self, upload):
        return self.client.post(self.url, {"step": "preview", "file": upload})

    def preview_rows(self, *rows, columns=None):
        return self.preview(csv_file([{**GOOD, **row} for row in rows], columns)).context["preview"]

    def do_import(self):
        return self.client.post(self.url, {"step": "import"}, follow=True)

    def demo_file(self):
        content = (settings.BASE_DIR / "data" / "demo_upload.csv").read_bytes()
        return SimpleUploadedFile("demo_upload.csv", content, content_type="text/csv")


class DemoUploadTests(UploadTestCase):
    def test_preview_rejects_clm_2003_with_a_clear_message(self):
        response = self.preview(self.demo_file())
        rows = response.context["preview"]
        self.assertEqual([item["row"]["claim_id"] for item in rows], ["CLM-2001", "CLM-2002", "CLM-2003"])
        self.assertEqual([bool(item["errors"]) for item in rows], [False, False, True])
        self.assertEqual(rows[2]["errors"], ["Date of service is missing"])
        self.assertContains(response, "Not imported: Date of service is missing.")
        self.assertEqual((response.context["valid_count"], response.context["invalid_count"]), (2, 1))
        self.assertContains(response, "Import 2 valid rows")
        # Nothing is imported at the preview step.
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS)

    def test_import_adds_two_claims_for_the_uploader_and_skips_one(self):
        self.preview(self.demo_file())
        response = self.do_import()
        self.assertRedirects(response, self.url)
        self.assertContains(response, "Upload complete. 2 imported, 1 skipped.")
        self.assertEqual(response.context["summary"], {"imported": 2, "skipped": 1})
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS + 2)
        self.assertFalse(Claim.objects.filter(claim_id="CLM-2003").exists())
        for claim_id in ("CLM-2001", "CLM-2002"):
            claim = Claim.objects.get(claim_id=claim_id)
            self.assertEqual((claim.assigned_to, claim.work_status), (self.maria, WorkStatus.NEW))
        queue_ids = [claim.claim_id for claim in self.client.get(reverse("queue")).context["claims"]]
        self.assertIn("CLM-2001", queue_ids)
        self.assertIn("CLM-2002", queue_ids)

    def test_uploaded_answer_key_is_stored_for_scoring_but_never_shown(self):
        response = self.preview(self.demo_file())
        self.assertNotContains(response, "Injury codes need a 7th character. This is the first visit")
        self.assertNotContains(response, "expected_")
        self.do_import()
        claim = Claim.objects.get(claim_id="CLM-2002")
        self.assertEqual((claim.expected_action, claim.expected_value), ("fix", "S61.411A"))
        page = self.client.get(reverse("claim", args=[claim.pk]))
        self.assertNotContains(page, claim.expected_issue)

    def test_import_needs_a_preview_first_and_runs_once(self):
        response = self.do_import()
        self.assertContains(response, "Preview a file before importing.")
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS)
        self.preview(self.demo_file())
        self.do_import()
        self.do_import()
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS + 2)


class RowValidationTests(UploadTestCase):
    def errors(self, **row):
        return self.preview_rows(row)[0]["errors"]

    def test_good_row_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_each_required_value(self):
        labels = {"claim_id": "Claim ID", "patient_first": "First name", "patient_last": "Last name", "payer_name": "Payer",
                  "date_of_service": "Date of service", "cpt_1": "CPT (line 1)", "icd10_primary": "Primary ICD-10"}
        for name, label in labels.items():
            self.assertEqual(self.errors(**{name: ""}), [f"{label} is missing"])

    def test_duplicate_of_an_existing_claim(self):
        self.assertEqual(self.errors(claim_id="CLM-1001"), ["Claim ID CLM-1001 is already in use"])

    def test_duplicate_inside_the_file(self):
        rows = self.preview_rows({}, {})
        self.assertEqual(rows[0]["errors"], [])
        self.assertEqual(rows[1]["errors"], ["Claim ID CLM-3001 is already in use"])

    def test_unknown_payer(self):
        self.assertEqual(self.errors(payer_name="Acme Health"), ["payer Acme Health is not in the payer rules"])
        self.assertEqual(self.errors(payer_name="All payers"), ["payer All payers is not in the payer rules"])

    def test_dates_must_be_yyyy_mm_dd(self):
        message = "Date of service must be a real date written as YYYY-MM-DD"
        for bad in ("11/01/2026", "2026-13-01", "2026-02-30", "20261101", "2026-1-1"):
            self.assertEqual(self.errors(date_of_service=bad), [message], bad)
        rows = self.preview_rows({"patient_dob": "01/02/1980"}, columns=[*GOOD, "patient_dob"])
        self.assertEqual(rows[0]["errors"], ["Date of birth must be a real date written as YYYY-MM-DD"])

    def test_status_units_and_charges(self):
        columns = [*GOOD, "status", "units_1", "charge_1"]
        rows = self.preview_rows({"status": "paid", "units_1": "two", "charge_1": "lots"}, columns=columns)
        self.assertEqual(
            rows[0]["errors"],
            ["Status must be new or denied", "Units (line 1) must be a whole number", "Charge (line 1) must be an amount such as 150.00"],
        )

    def test_text_that_is_too_long_is_caught(self):
        errors = self.errors(cpt_1="9" * 40)
        self.assertEqual(len(errors), 1)
        self.assertIn("CPT (line 1)", errors[0])

    def test_answer_key_columns_are_optional_and_such_claims_are_not_scored(self):
        self.assertFalse(set(GOOD) & set(ANSWER_KEY_FIELDS))
        self.preview(csv_file([GOOD]))
        self.do_import()
        claim = Claim.objects.get(claim_id="CLM-3001")
        self.assertEqual(claim.expected_action, "")
        score_claim(claim, self.maria, FinalAction.SUBMIT)
        self.assertEqual(Attempt.objects.exclude(worker__username="cassandra").count(), 0)

    def test_only_valid_rows_are_imported(self):
        self.preview(csv_file([GOOD, {**GOOD, "claim_id": "CLM-3002", "payer_name": "Acme"}, {**GOOD, "claim_id": "CLM-3003"}]))
        response = self.do_import()
        self.assertContains(response, "Upload complete. 2 imported, 1 skipped.")
        self.assertEqual(set(Claim.objects.filter(claim_id__startswith="CLM-30").values_list("claim_id", flat=True)), {"CLM-3001", "CLM-3003"})


class FileValidationTests(UploadTestCase):
    def test_no_file(self):
        self.assertContains(self.client.post(self.url, {"step": "preview"}), "Choose a CSV file first.")

    def test_missing_required_columns(self):
        response = self.preview(csv_file([{"claim_id": "CLM-3001", "cpt_1": "99213"}]))
        self.assertContains(response, "The file is missing required columns: patient_first, patient_last, payer_name, date_of_service, icd10_primary.")
        self.assertNotIn("preview", response.context)

    def test_empty_and_unreadable_files(self):
        self.assertContains(self.preview(csv_file([], columns=list(GOOD))), "The file has no claim rows.")
        binary = SimpleUploadedFile("claims.csv", b"\xff\xfe\x00\x01\x80\x81", content_type="text/csv")
        self.assertContains(self.preview(binary), "That file could not be read.")

    def test_a_bad_file_clears_an_earlier_preview(self):
        self.preview(self.demo_file())
        self.client.post(self.url, {"step": "preview"})
        self.do_import()
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS)


class UploadPageTests(UploadTestCase):
    def test_page_has_drop_zone_and_template_link(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'type="file"')
        self.assertContains(response, "Drop a CSV file here, or click to choose one")
        self.assertContains(response, reverse("upload_template"))
        self.assertContains(self.client.get(reverse("queue")), f'href="{self.url}"')

    def test_template_download_is_the_header_row_of_sample_claims(self):
        response = self.client.get(reverse("upload_template"))
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])
        header = (settings.BASE_DIR / "data" / "sample_claims.csv").read_text().splitlines()[0]
        self.assertEqual(response.content.decode().strip(), header)
        self.assertEqual(header.split(","), CSV_COLUMNS)

    def test_specialists_can_upload_their_own_claims(self):
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.preview(self.demo_file())
        self.do_import()
        claim = Claim.objects.get(claim_id="CLM-2001")
        self.assertEqual((claim.assigned_to, claim.organization), (self.dan, self.ags))
