"""End-to-end tests: real OCR on the bundled sample labels, through the HTTP API.

Requires the Tesseract binary. Regenerate samples with `python scripts/generate_samples.py`.
"""
import csv
import io
import shutil
import time
import unittest
from pathlib import Path

from app import create_app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
LATENCY_BUDGET_S = 5.0

# Expected overall result per sample. The photo sample may land on review on some
# Tesseract builds (bold can't always be confirmed on a blurry photo).
EXPECTED = {
    "01_old_tom_pass.png": {"pass"},
    "02_stones_throw_case_diff.png": {"pass"},
    "03_warning_title_case.png": {"fail"},
    "04_wrong_abv.png": {"fail"},
    "05_warning_reworded.png": {"fail"},
    "06_header_not_bold.png": {"review"},
    "07_photo_tilt_glare.jpg": {"pass", "review"},
    "08_imported_beer_units.png": {"pass"},
    "09_wrong_brand.png": {"fail"},
}


def manifest_rows():
    with (SAMPLES / "batch_manifest.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless(shutil.which("tesseract"), "tesseract not installed")
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_app().test_client()

    def _verify(self, row):
        data = {k: v for k, v in row.items() if k not in ("filename", "expected_outcome")}
        data["image"] = (io.BytesIO((SAMPLES / row["filename"]).read_bytes()), row["filename"])
        return self.client.post("/api/verify", data=data, content_type="multipart/form-data")

    def test_samples_match_expected_outcomes_within_budget(self):
        for row in manifest_rows():
            with self.subTest(sample=row["filename"]):
                start = time.perf_counter()
                resp = self._verify(row)
                elapsed = time.perf_counter() - start
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertIn(resp.get_json()["overall"], EXPECTED[row["filename"]])
                self.assertLess(elapsed, LATENCY_BUDGET_S)

    def test_rejects_non_image(self):
        resp = self.client.post("/api/verify", data={"image": (io.BytesIO(b"hello"), "x.png")},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("readable image", resp.get_json()["error"])

    def test_rejects_missing_image(self):
        resp = self.client.post("/api/verify", data={}, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)

    def test_batch_flow(self):
        rows = manifest_rows()[:3]
        manifest = io.StringIO()
        w = csv.DictWriter(manifest, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        files = [(io.BytesIO((SAMPLES / r["filename"]).read_bytes()), r["filename"]) for r in rows]
        files.append((io.BytesIO(b"\x89PNG not really"), "orphan.png"))  # no manifest row
        resp = self.client.post("/api/batch", data={
            "images": files,
            "manifest": (io.BytesIO(manifest.getvalue().encode()), "m.csv"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 202)
        job_id = resp.get_json()["id"]

        deadline = time.time() + 60
        while time.time() < deadline:
            job = self.client.get(f"/api/batch/{job_id}").get_json()
            if job["done"]:
                break
            time.sleep(0.3)
        self.assertTrue(job["done"])
        self.assertEqual(job["counts"]["error"], 1)
        self.assertEqual(job["completed"], 4)

        csv_resp = self.client.get(f"/api/batch/{job_id}/results.csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("01_old_tom_pass.png,pass", csv_resp.get_data(as_text=True))

    def test_batch_manifest_validation(self):
        resp = self.client.post("/api/batch", data={
            "images": [(io.BytesIO(b"x"), "a.png")],
            "manifest": (io.BytesIO(b"name,brand\nx,y\n"), "m.csv"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("filename", resp.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
