"""Unicode search normalization and service-layer validation tests."""

import pytest

from retvia.core.errors import ValidationError
from retvia.core.textnorm import like_pattern, normalize_phone, normalize_search
from retvia.core.validation import (
    require_percent_bp,
    require_text,
    validate_barcode,
    validate_date_range,
    validate_email,
    validate_phone,
    validate_sku,
)


class TestNormalizeSearch:
    def test_case_insensitive(self):
        assert normalize_search("Sugar") == normalize_search("sugar")

    def test_bangla_digits_match_english(self):
        assert normalize_search("চিনি ১ কেজি") == normalize_search("চিনি 1 কেজি")

    def test_whitespace_collapsed(self):
        assert normalize_search("  চিনি   চিনি  ") == "চিনি চিনি"

    def test_bengali_preserved(self):
        assert normalize_search("সয়াবিন তেল") == "সয়াবিন তেল"

    def test_none_and_empty(self):
        assert normalize_search(None) == ""
        assert normalize_search("") == ""

    def test_mixed_language(self):
        assert normalize_search("Pran চিনি") == "pran চিনি"


class TestLikePattern:
    def test_wildcards_escaped(self):
        assert like_pattern("100%") == "%100\\%%"
        assert like_pattern("a_b") == "%a\\_b%"

    def test_backslash_escaped(self):
        assert like_pattern("a\\b") == "%a\\\\b%"


class TestPhone:
    @pytest.mark.parametrize(
        "raw",
        ["+8801712345678", "8801712345678", "01712345678", "০১৭১২৩৪৫৬৭৮", "01712-345678"],
    )
    def test_normalizes_to_same(self, raw):
        assert normalize_phone(raw) == "01712345678"

    def test_validation_rejects_short(self):
        with pytest.raises(ValidationError):
            validate_phone("123")

    def test_optional_empty(self):
        assert validate_phone("") == ""
        assert validate_phone(None) == ""

    def test_required_empty_raises(self):
        with pytest.raises(ValidationError):
            validate_phone("", required=True)


class TestTextValidation:
    def test_required(self):
        assert require_text("  চাল  ") == "চাল"
        with pytest.raises(ValidationError, match="আবশ্যক"):
            require_text("   ", "প্রোডাক্টের নাম")

    def test_control_characters_stripped(self):
        assert require_text("চাল\x00\x01") == "চাল"

    def test_max_length(self):
        assert len(require_text("ক" * 300, "নাম", max_length=50)) == 50

    def test_sku(self):
        assert validate_sku("RICE-001") == "RICE-001"
        with pytest.raises(ValidationError):
            validate_sku("bad sku!")

    def test_barcode(self):
        assert validate_barcode("8901234567890") == "8901234567890"
        with pytest.raises(ValidationError):
            validate_barcode("bad code!")

    def test_email(self):
        assert validate_email("a@b.com") == "a@b.com"
        assert validate_email("") == ""
        with pytest.raises(ValidationError):
            validate_email("not-an-email")

    def test_percent_bounds(self):
        assert require_percent_bp(1000, "ডিস্কাউন্ট") == 1000
        with pytest.raises(ValidationError):
            require_percent_bp(-1, "ডিস্কাউন্ট")
        with pytest.raises(ValidationError):
            require_percent_bp(10_001, "ডিস্কাউন্ট")


class TestDates:
    def test_range(self):
        assert validate_date_range("2026-01-01", "2026-01-31") == ("2026-01-01", "2026-01-31")

    def test_bangla_digits_in_date(self):
        assert validate_date_range("২০২৬-০১-০১", "2026-01-31")[0] == "2026-01-01"

    def test_reversed_range_rejected(self):
        with pytest.raises(ValidationError):
            validate_date_range("2026-02-01", "2026-01-01")

    def test_invalid_date(self):
        with pytest.raises(ValidationError):
            validate_date_range("2026-13-01", "2026-01-01")
