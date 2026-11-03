"""Financial core tests — the highest-risk area of the product."""

from decimal import Decimal

import pytest

from retvia.core.money import (
    allocate,
    format_money,
    normalize_digits,
    parse_money,
    percent_of,
    percent_to_basis_points,
    round_div,
)


class TestRoundDiv:
    def test_half_rounds_away_from_zero(self):
        assert round_div(5, 2) == 3
        assert round_div(-5, 2) == -3
        assert round_div(1, 2) == 1
        assert round_div(-1, 2) == -1

    def test_exact_division(self):
        assert round_div(10, 5) == 2
        assert round_div(-10, 5) == -2
        assert round_div(0, 7) == 0

    def test_thirds(self):
        assert round_div(1, 3) == 0
        assert round_div(2, 3) == 1
        assert round_div(100, 3) == 33
        assert round_div(200, 3) == 67

    def test_negative_denominator_normalizes(self):
        assert round_div(5, -2) == -3
        assert round_div(-5, -2) == 3

    def test_zero_denominator_raises(self):
        with pytest.raises(ZeroDivisionError):
            round_div(1, 0)

    def test_never_uses_float_for_large_values(self):
        # 10^15 poisha is far beyond float's exact integer range.
        huge = 10**15 + 1
        assert round_div(huge * 3, 3) == huge


class TestParseMoney:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0", 0),
            ("1", 100),
            ("12.34", 1234),
            ("12.345", 1235),  # half up
            ("12.344", 1234),
            ("-5.00", -500),
            ("1,250.00", 125000),
            ("৳ 99.99", 9999),
            ("  42.50  ", 4250),
            ("BDT 10", 1000),
            ("", 0),
            (None, 0),
        ],
    )
    def test_parses(self, text, expected):
        assert parse_money(text) == expected

    def test_bangla_digits(self):
        assert parse_money("১২৩.৪৫") == 12345
        assert parse_money("০.০১") == 1
        assert parse_money("১,০০০") == 100000

    def test_bangla_and_english_are_identical(self):
        assert parse_money("৯৮৭.৬৫") == parse_money("987.65")

    def test_decimal_and_int_inputs(self):
        assert parse_money(Decimal("19.99")) == 1999
        assert parse_money(25) == 2500

    def test_invalid_text_raises_bangla_error(self):
        with pytest.raises(ValueError, match="টাকার পরিমাণ"):
            parse_money("abc")

    def test_infinite_rejected(self):
        with pytest.raises(ValueError):
            parse_money(Decimal("Infinity"))

    def test_no_float_accumulation_error(self):
        # 0.1 + 0.2 must be exactly 0.30 in poisha.
        assert parse_money("0.1") + parse_money("0.2") == parse_money("0.3")

    def test_ten_thousand_small_additions_are_exact(self):
        total = sum(parse_money("0.01") for _ in range(10_000))
        assert total == parse_money("100.00")


class TestFormatMoney:
    def test_basic(self):
        assert format_money(123456) == "1,234.56"
        assert format_money(0) == "0.00"
        assert format_money(5) == "0.05"

    def test_south_asian_grouping(self):
        assert format_money(1234567890) == "1,23,45,678.90"
        assert format_money(100000) == "1,000.00"

    def test_negative(self):
        assert format_money(-123456) == "-1,234.56"

    def test_symbol_and_decimals(self):
        assert format_money(123456, symbol="৳ ") == "৳ 1,234.56"
        assert format_money(123456, decimals=0) == "1,235"
        assert format_money(123450, decimals=1) == "1,234.5"

    def test_bangla_digit_output(self):
        out = format_money(12345, bangla_digits=True)
        assert out == "১২৩.৪৫"
        assert normalize_digits(out) == "123.45"

    def test_roundtrip(self):
        for value in (0, 1, 99, 100, 12345, 999999999):
            assert parse_money(format_money(value, grouping=False)) == value


class TestPercent:
    def test_percent_of(self):
        assert percent_of(10000, 1000) == 1000  # 10% of 100.00
        assert percent_of(10000, 750) == 750  # 7.5%
        assert percent_of(1, 5000) == 1  # half up on 0.5
        assert percent_of(0, 1000) == 0

    def test_basis_point_parsing(self):
        assert percent_to_basis_points("10") == 1000
        assert percent_to_basis_points("7.5") == 750
        assert percent_to_basis_points("১৫") == 1500
        assert percent_to_basis_points(5) == 500
        assert percent_to_basis_points("0.01") == 1

    def test_full_percentage(self):
        assert percent_of(54321, 10_000) == 54321


class TestAllocate:
    def test_sums_exactly(self):
        assert sum(allocate(100, [1, 1, 1])) == 100
        assert allocate(100, [1, 1, 1]) == [34, 33, 33]

    def test_proportional(self):
        assert allocate(1000, [100, 300, 600]) == [100, 300, 600]

    def test_uneven_weights_sum_exactly(self):
        weights = [3333, 6667, 1234, 9999]
        for total in (1, 7, 101, 99999, 123457):
            result = allocate(total, weights)
            assert sum(result) == total
            assert all(x >= 0 for x in result)

    def test_zero_total(self):
        assert allocate(0, [5, 5, 5]) == [0, 0, 0]

    def test_zero_weights_spreads_evenly(self):
        assert allocate(10, [0, 0, 0]) == [4, 3, 3]
        assert sum(allocate(10, [0, 0, 0])) == 10

    def test_negative_total(self):
        result = allocate(-100, [1, 1, 1])
        assert sum(result) == -100
        assert result == [-34, -33, -33]

    def test_empty_weights(self):
        assert allocate(0, []) == []
        with pytest.raises(ValueError):
            allocate(5, [])

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            allocate(100, [1, -1])

    def test_single_weight_gets_everything(self):
        assert allocate(12345, [7]) == [12345]

    def test_invoice_discount_reconciles(self):
        """Line revenues after an invoice discount must sum to the invoice total."""
        line_nets = [13333, 26667, 9999]
        invoice_discount = 5000
        allocated = allocate(invoice_discount, line_nets)
        revenues = [n - a for n, a in zip(line_nets, allocated, strict=False)]
        assert sum(revenues) == sum(line_nets) - invoice_discount
        assert sum(allocated) == invoice_discount
