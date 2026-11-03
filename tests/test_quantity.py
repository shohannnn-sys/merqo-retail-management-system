"""Quantity core tests — exact decimal quantities without float drift."""

from decimal import Decimal

import pytest

from retvia.core.quantity import (
    format_quantity,
    line_total,
    parse_quantity,
    to_units,
    unit_cost_from_total,
)


class TestParseQuantity:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1", 1000),
            ("1.5", 1500),
            ("0.001", 1),
            ("0.25", 250),
            ("12.3456", 12346),  # rounded to 3 dp
            ("-2.5", -2500),
            ("1,000", 1000000),
            ("", 0),
            (None, 0),
        ],
    )
    def test_parses(self, text, expected):
        assert parse_quantity(text) == expected

    def test_bangla_digits(self):
        assert parse_quantity("০.২৫০") == 250
        assert parse_quantity("৩.৫") == 3500

    def test_precision_zero_forces_whole_units(self):
        assert parse_quantity("2.4", precision=0) == 2000
        assert parse_quantity("2.5", precision=0) == 3000

    def test_precision_two(self):
        assert parse_quantity("1.239", precision=2) == 1240

    def test_invalid_precision_rejected(self):
        with pytest.raises(ValueError):
            parse_quantity("1", precision=4)
        with pytest.raises(ValueError):
            parse_quantity("1", precision=-1)

    def test_invalid_text(self):
        with pytest.raises(ValueError, match="পরিমাণ"):
            parse_quantity("abc")

    def test_exact_accumulation(self):
        total = sum(parse_quantity("0.001") for _ in range(1000))
        assert total == parse_quantity("1")


class TestFormatQuantity:
    def test_trims_trailing_zeros(self):
        assert format_quantity(1500) == "1.5"
        assert format_quantity(1000) == "1"
        assert format_quantity(250) == "0.25"

    def test_no_trim(self):
        assert format_quantity(1500, trim=False) == "1.500"

    def test_precision(self):
        assert format_quantity(1234, precision=2) == "1.23"
        assert format_quantity(1500, precision=0) == "2"

    def test_negative(self):
        assert format_quantity(-1500) == "-1.5"

    def test_roundtrip(self):
        for milli in (0, 1, 250, 1000, 1500, 123456):
            assert parse_quantity(format_quantity(milli)) == milli


class TestLineTotal:
    def test_price_times_quantity(self):
        assert line_total(1250, 1500) == 1875  # 12.50 × 1.5 = 18.75
        assert line_total(10000, 2000) == 20000  # 100.00 × 2
        assert line_total(333, 3000) == 999

    def test_fractional_rounding_half_up(self):
        assert line_total(1, 500) == 1  # 0.01 × 0.5 = 0.005 -> 0.01
        assert line_total(1, 499) == 0

    def test_zero_quantity(self):
        assert line_total(5000, 0) == 0

    def test_large_quantity_exact(self):
        assert line_total(99999, 1_000_000) == 99999000


class TestUnitCostFromTotal:
    def test_inverse_of_line_total(self):
        assert unit_cost_from_total(1875, 1500) == 1250

    def test_zero_quantity_raises(self):
        with pytest.raises(ZeroDivisionError):
            unit_cost_from_total(100, 0)


def test_to_units_is_exact_decimal():
    assert to_units(1500) == Decimal("1.5")
    assert to_units(1) == Decimal("0.001")
