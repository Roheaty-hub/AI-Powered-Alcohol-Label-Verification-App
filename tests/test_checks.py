"""Unit tests for the field checks. These operate on plain OCR text — no images needed."""
import unittest

from app.checks.alcohol import check_alcohol, parse_expected_abv
from app.checks.net_contents import check_net_contents, find_quantities
from app.checks.normalize import canonical
from app.checks.text_fields import check_text_field
from app.checks.warning import BODY, check_warning
from app.models import BeverageType, OcrResult, Status

GOOD_WARNING = "GOVERNMENT WARNING: " + BODY


def ocr(text: str) -> OcrResult:
    return OcrResult(words=[], text=text, mean_confidence=95, variant="test", elapsed_ms=0)


class NormalizeTests(unittest.TestCase):
    def test_case_quotes_and_punctuation_ignored(self):
        self.assertEqual(canonical("STONE'S THROW"), canonical("Stone’s Throw"))

    def test_decimal_points_preserved(self):
        self.assertEqual(canonical("Alc. 12.5% Vol."), "alc 12.5% vol")


class TextFieldTests(unittest.TestCase):
    def test_daves_stones_throw_case(self):
        r = check_text_field("brand_name", "Brand", "Stone's Throw", "STONE'S THROW\nLondon Dry Gin")
        self.assertEqual(r.status, Status.PASS)
        self.assertIn("capitalization", r.message)

    def test_ocr_misread_goes_to_review(self):
        r = check_text_field("brand_name", "Brand", "OLD TOM DISTILLERY", "OLD T0M DISTILLFRY")
        self.assertEqual(r.status, Status.REVIEW)

    def test_split_word_still_passes(self):
        r = check_text_field("brand_name", "Brand", "OLD TOM DISTILLERY", "OLD TOM DIST ILLERY")
        self.assertEqual(r.status, Status.PASS)

    def test_different_brand_fails(self):
        r = check_text_field("brand_name", "Brand", "Blue Ridge Spirits", "OLD TOM DISTILLERY")
        self.assertEqual(r.status, Status.FAIL)

    def test_optional_blank_skipped(self):
        r = check_text_field("bottler", "Bottler", "", "anything", required=False)
        self.assertEqual(r.status, Status.SKIPPED)


class AlcoholTests(unittest.TestCase):
    def test_parse_variants(self):
        self.assertEqual(parse_expected_abv("45%"), 45)
        self.assertEqual(parse_expected_abv("45% Alc./Vol. (90 Proof)"), 45)
        self.assertEqual(parse_expected_abv("90 Proof"), 45)
        self.assertEqual(parse_expected_abv("12.5"), 12.5)

    def test_match_with_consistent_proof(self):
        r = check_alcohol("45%", "45% Alc./Vol. (90 Proof)", BeverageType.SPIRITS)
        self.assertEqual(r.status, Status.PASS)

    def test_mismatch(self):
        r = check_alcohol("45%", "40% Alc./Vol. (80 Proof)", BeverageType.SPIRITS)
        self.assertEqual(r.status, Status.FAIL)
        self.assertIn("40%", r.message)

    def test_inconsistent_proof_flags_review(self):
        r = check_alcohol("45%", "45% Alc./Vol. (80 Proof)", BeverageType.SPIRITS)
        self.assertEqual(r.status, Status.REVIEW)

    def test_ocr_letter_o_for_zero(self):
        r = check_alcohol("40%", "4O% ALC/VOL", BeverageType.SPIRITS)
        self.assertEqual(r.status, Status.PASS)

    def test_blank_optional_for_beer(self):
        r = check_alcohol("", "no abv here", BeverageType.BEER)
        self.assertEqual(r.status, Status.SKIPPED)

    def test_blank_required_for_spirits(self):
        self.assertEqual(check_alcohol("", "45%", BeverageType.SPIRITS).status, Status.FAIL)


class NetContentsTests(unittest.TestCase):
    def test_same_units(self):
        self.assertEqual(check_net_contents("750 mL", "Net 750 ML").status, Status.PASS)

    def test_unit_conversion(self):
        self.assertEqual(check_net_contents("750 mL", "75 cl").status, Status.PASS)
        self.assertEqual(check_net_contents("355 mL", "12 FL. OZ.").status, Status.PASS)
        self.assertEqual(check_net_contents("1 L", "1000 ml").status, Status.PASS)

    def test_mismatch(self):
        r = check_net_contents("750 mL", "1 L")
        self.assertEqual(r.status, Status.FAIL)

    def test_warning_numbers_not_quantities(self):
        self.assertEqual(find_quantities(GOOD_WARNING), [])


class WarningTests(unittest.TestCase):
    def test_exact_warning_passes_text_checks(self):
        r = check_warning(ocr(GOOD_WARNING))
        # No image supplied, so bold can't be measured -> REVIEW, but nothing fails.
        self.assertEqual(r.status, Status.REVIEW)
        self.assertTrue(any("exactly" in d for d in r.details))

    def test_title_case_header_fails(self):
        r = check_warning(ocr("Government Warning: " + BODY))
        self.assertEqual(r.status, Status.FAIL)
        self.assertTrue(any("ALL CAPS" in d for d in r.details))

    def test_reworded_body_fails(self):
        r = check_warning(ocr("GOVERNMENT WARNING: " + BODY.replace("birth defects", "health issues")))
        self.assertEqual(r.status, Status.FAIL)

    def test_missing_warning_fails(self):
        self.assertEqual(check_warning(ocr("OLD TOM 45% 750 mL")).status, Status.FAIL)

    def test_single_ocr_typo_is_review_not_fail(self):
        r = check_warning(ocr("GOVERNMENT WARNING: " + BODY.replace("pregnancy", "pregnaney")))
        self.assertEqual(r.status, Status.REVIEW)

    def test_trailing_label_text_ignored(self):
        r = check_warning(ocr(GOOD_WARNING + " Bottled in Kentucky. Please recycle."))
        self.assertTrue(any("exactly" in d for d in r.details))


if __name__ == "__main__":
    unittest.main()
