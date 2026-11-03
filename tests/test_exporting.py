"""Export service: Excel-safe CSV, formatted XLSX and format dispatch."""

from __future__ import annotations

import csv
import io
import zipfile

import pytest

from retvia.core.errors import ValidationError
from retvia.services.exporting import EXCEL_MONEY_FORMAT, EXCEL_QTY_FORMAT, ExportService
from retvia.services.reports import Column, ReportResult
from retvia.services.settings import BusinessProfile


@pytest.fixture
def exporter(settings, db):
    from retvia.services.settings import BusinessProfileService

    profile = BusinessProfileService(db)
    profile.update(BusinessProfile(name="রহমান স্টোর", address="টাঙ্গাইল", phone="01711111111"))
    return ExportService(settings, profile)


@pytest.fixture
def result():
    return ReportResult(
        id="sales_summary",
        title="সেলস সামারি রিপোর্ট",
        columns=[
            Column("invoice_no", "ইনভয়েস নং"),
            Column("customer", "কাস্টমার"),
            Column("qty", "পরিমাণ", "qty", total=True),
            Column("amount", "মোট টাকা", "money", total=True),
            Column("count", "সংখ্যা", "int", total=True),
        ],
        rows=[
            {
                "invoice_no": "INV-2026-00001",
                "customer": "করিম মিয়া",
                "qty": 2500,
                "amount": 125050,
                "count": 2,
            },
            {
                "invoice_no": "INV-2026-00002",
                "customer": 'রহিম, "স্টোর"',
                "qty": 1000,
                "amount": -5000,
                "count": 1,
            },
        ],
        totals={"qty": 3500, "amount": 120050, "count": 3},
        meta={"filters": {"start": "2026-01-01", "end": "2026-01-31"}},
    )


class TestCsv:
    def test_starts_with_utf8_bom_for_excel(self, exporter, result, tmp_path):
        path = exporter.to_csv(result, tmp_path / "r.csv")
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), "Excel needs a BOM to detect UTF-8"

    def test_bangla_round_trips(self, exporter, result, tmp_path):
        path = exporter.to_csv(result, tmp_path / "r.csv")
        text = path.read_text(encoding="utf-8-sig")
        assert "সেলস সামারি রিপোর্ট" in text
        assert "করিম মিয়া" in text
        assert "ইনভয়েস নং" in text

    def test_header_and_rows_are_parseable(self, exporter, result, tmp_path):
        path = exporter.to_csv(result, tmp_path / "r.csv")
        text = path.read_text(encoding="utf-8-sig")
        # Business/title preamble lines precede the column header row.
        start = next(i for i, line in enumerate(text.splitlines()) if line.startswith("ইনভয়েস নং"))
        reader = list(csv.reader(io.StringIO("\n".join(text.splitlines()[start:]))))
        assert reader[0] == ["ইনভয়েস নং", "কাস্টমার", "পরিমাণ", "মোট টাকা", "সংখ্যা"]
        assert reader[1][0] == "INV-2026-00001"
        assert reader[1][3] == "1250.50"
        assert reader[2][1] == 'রহিম, "স্টোর"', "commas and quotes must be escaped by the writer"

    def test_totals_row_present(self, exporter, result, tmp_path):
        path = exporter.to_csv(result, tmp_path / "r.csv")
        text = path.read_text(encoding="utf-8-sig")
        assert "মোট" in text
        assert "1200.50" in text

    def test_money_converted_from_poisha(self, exporter, result, tmp_path):
        path = exporter.to_csv(result, tmp_path / "r.csv")
        assert "125050" not in path.read_text(encoding="utf-8-sig")

    def test_empty_result_still_writes_header(self, exporter, tmp_path):
        empty = ReportResult("x", "খালি রিপোর্ট", [Column("a", "কলাম")], [], {}, {})
        path = exporter.to_csv(empty, tmp_path / "empty.csv")
        assert "কলাম" in path.read_text(encoding="utf-8-sig")

    def test_creates_missing_parent_directory(self, exporter, result, tmp_path):
        path = exporter.to_csv(result, tmp_path / "nested" / "deep" / "r.csv")
        assert path.is_file()


class TestXlsx:
    def test_is_a_real_xlsx_archive(self, exporter, result, tmp_path):
        path = exporter.to_xlsx(result, tmp_path / "r.xlsx")
        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path) as archive:
            assert "xl/worksheets/sheet1.xml" in archive.namelist()

    def test_money_and_quantity_number_formats(self, exporter, result, tmp_path):
        from openpyxl import load_workbook

        path = exporter.to_xlsx(result, tmp_path / "r.xlsx")
        book = load_workbook(path)
        sheet = book.active
        header_row = 4
        headers = [c.value for c in sheet[header_row]]
        assert headers[:5] == ["ইনভয়েস নং", "কাস্টমার", "পরিমাণ", "মোট টাকা", "সংখ্যা"]
        first = sheet[header_row + 1]
        assert first[2].number_format == EXCEL_QTY_FORMAT
        assert first[3].number_format == EXCEL_MONEY_FORMAT
        assert first[3].value == pytest.approx(1250.50)
        assert first[2].value == pytest.approx(2.5)
        book.close()

    def test_bangla_headers_and_values(self, exporter, result, tmp_path):
        from openpyxl import load_workbook

        book = load_workbook(exporter.to_xlsx(result, tmp_path / "r.xlsx"))
        values = [str(c.value) for row in book.active.iter_rows() for c in row if c.value is not None]
        assert any("সেলস সামারি রিপোর্ট" in v for v in values)
        assert "করিম মিয়া" in values
        book.close()

    def test_freeze_panes_and_autofilter(self, exporter, result, tmp_path):
        from openpyxl import load_workbook

        book = load_workbook(exporter.to_xlsx(result, tmp_path / "r.xlsx"))
        sheet = book.active
        assert sheet.freeze_panes is not None
        assert sheet.auto_filter.ref is not None
        book.close()

    def test_totals_row_written(self, exporter, result, tmp_path):
        from openpyxl import load_workbook

        book = load_workbook(exporter.to_xlsx(result, tmp_path / "r.xlsx"))
        values = [c.value for row in book.active.iter_rows() for c in row]
        assert pytest.approx(1200.50) in [v for v in values if isinstance(v, int | float)]
        book.close()

    def test_negative_money_kept_negative(self, exporter, result, tmp_path):
        from openpyxl import load_workbook

        book = load_workbook(exporter.to_xlsx(result, tmp_path / "r.xlsx"))
        row = book.active[6]
        assert row[3].value == pytest.approx(-50.0)
        book.close()


class TestDispatch:
    @pytest.mark.parametrize("fmt,suffix", [("csv", ".csv"), ("xlsx", ".xlsx"), ("excel", ".xlsx")])
    def test_export_dispatch(self, exporter, result, tmp_path, fmt, suffix):
        path = exporter.export(result, tmp_path / f"out{suffix}", fmt)
        assert path.is_file()
        assert path.suffix == suffix

    def test_unknown_format_rejected(self, exporter, result, tmp_path):
        with pytest.raises(ValidationError):
            exporter.export(result, tmp_path / "out.txt", "txt")

    def test_extension_added_when_missing(self, exporter, result, tmp_path):
        path = exporter.export(result, tmp_path / "noext", "csv")
        assert path.name.endswith(".csv")

    def test_real_report_exports(self, db, settings, tmp_path):
        from retvia.services.reports import ReportService
        from retvia.services.settings import BusinessProfileService

        profile = BusinessProfileService(db)
        service = ExportService(settings, profile)
        reports = ReportService(db, settings)
        for report_id in ("daily_sales", "stock", "profit_loss"):
            result = reports.run(report_id, {})
            csv_path = service.export(result, tmp_path / f"{report_id}.csv", "csv")
            xlsx_path = service.export(result, tmp_path / f"{report_id}.xlsx", "xlsx")
            assert csv_path.stat().st_size > 0
            assert xlsx_path.stat().st_size > 0
