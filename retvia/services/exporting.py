"""Report export to CSV, Excel and PDF.

* CSV  — UTF-8 **with BOM** so Excel opens Bengali correctly.
* XLSX — real number/date/currency formats, totals row, frozen header, Bangla font.
* PDF  — rendered through Qt so Bengali conjuncts shape exactly as on screen and
         the font is embedded. Qt is imported lazily so headless environments can
         still use the CSV and Excel exporters.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.errors import ValidationError
from ..core.money import format_money
from ..core.quantity import format_quantity
from .reports import Column, ReportResult
from .settings import BusinessProfileService, SettingsService

EXCEL_MONEY_FORMAT = "#,##0.00;[Red]-#,##0.00"
EXCEL_QTY_FORMAT = "#,##0.###"


class ExportService:
    def __init__(self, settings: SettingsService, profile: BusinessProfileService | None = None) -> None:
        self.settings = settings
        self.profile = profile

    # ------------------------------------------------------------- formatting
    def format_value(self, column: Column, value: Any) -> str:
        if value is None:
            return ""
        if column.kind == "money":
            return format_money(int(value), grouping=False)
        if column.kind == "qty":
            return format_quantity(int(value))
        if column.kind == "percent":
            return f"{int(value) / 100:.2f}%"
        return str(value)

    def _business_name(self) -> str:
        if self.profile is not None:
            return self.profile.get().name
        return ""

    def _filename(self, result: ReportResult, suffix: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{result.id}-{stamp}.{suffix}"

    def _target(self, result: ReportResult, path: Path | str, suffix: str) -> Path:
        """Resolve a directory, a bare name or a full filename into a real path."""
        target = Path(path)
        if target.is_dir():
            target = target / self._filename(result, suffix)
        elif target.suffix.lower() != f".{suffix}":
            target = target.with_name(f"{target.name}.{suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _preamble(self, result: ReportResult) -> list[list[str]]:
        """Business name and report title, matching the Excel and PDF layouts."""
        filters = result.meta.get("filters", {})
        title = result.title
        if filters.get("start"):
            title += f"  |  {filters['start']} — {filters.get('end', '')}"
        rows: list[list[str]] = []
        business = self._business_name()
        if business:
            rows.append([business])
        rows.append([title])
        rows.append([f"তৈরির সময়: {datetime.now().strftime('%Y-%m-%d %H:%M')}"])
        rows.append([])
        return rows

    # -------------------------------------------------------------------- CSV
    def to_csv(self, result: ReportResult, path: Path | str) -> Path:
        target = self._target(result, path, "csv")
        # utf-8-sig writes the BOM that Excel needs for Bengali text.
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            for line in self._preamble(result):
                writer.writerow(line)
            writer.writerow([c.label for c in result.columns])
            for row in result.rows:
                writer.writerow([self.format_value(c, row.get(c.key)) for c in result.columns])
            if result.totals:
                writer.writerow(
                    [
                        ("মোট" if index == 0 else self.format_value(c, result.totals.get(c.key, "")))
                        if c.key in result.totals or index == 0
                        else ""
                        for index, c in enumerate(result.columns)
                    ]
                )
        return target

    # ------------------------------------------------------------------- XLSX
    def to_xlsx(self, result: ReportResult, path: Path | str) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        target = self._target(result, path, "xlsx")
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Report"
        bangla_font = "Nirmala UI"
        header_fill = PatternFill("solid", fgColor="1F3A5F")
        header_font = Font(name=bangla_font, bold=True, color="FFFFFF", size=11)
        body_font = Font(name=bangla_font, size=10)
        thin = Side(style="thin", color="D8DEE7")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        business = self._business_name()
        sheet.append([business or result.title])
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(result.columns))
        sheet.cell(row=1, column=1).font = Font(name=bangla_font, bold=True, size=14)
        sheet.cell(row=1, column=1).alignment = Alignment(horizontal="center")

        filters = result.meta.get("filters", {})
        subtitle = result.title
        if filters.get("start"):
            subtitle += f"  |  {filters['start']} — {filters.get('end', '')}"
        sheet.append([subtitle])
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(result.columns))
        sheet.cell(row=2, column=1).font = Font(name=bangla_font, size=10, color="5A6472")
        sheet.cell(row=2, column=1).alignment = Alignment(horizontal="center")
        sheet.append([])

        header_row = 4
        sheet.append([c.label for c in result.columns])
        for index, _ in enumerate(result.columns, start=1):
            cell = sheet.cell(row=header_row, column=index)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        from decimal import Decimal

        for row in result.rows:
            values: list[Any] = []
            for column in result.columns:
                raw = row.get(column.key)
                if column.kind == "money" and raw is not None:
                    values.append(float(Decimal(int(raw)) / 100))
                elif column.kind == "qty" and raw is not None:
                    values.append(float(Decimal(int(raw)) / 1000))
                elif column.kind in ("int", "percent") and raw is not None:
                    values.append(int(raw))
                else:
                    values.append("" if raw is None else str(raw))
            sheet.append(values)
            current = sheet.max_row
            for index, column in enumerate(result.columns, start=1):
                cell = sheet.cell(row=current, column=index)
                cell.font = body_font
                cell.border = border
                if column.kind == "money":
                    cell.number_format = EXCEL_MONEY_FORMAT
                    cell.alignment = Alignment(horizontal="right")
                elif column.kind == "qty":
                    cell.number_format = EXCEL_QTY_FORMAT
                    cell.alignment = Alignment(horizontal="right")
                elif column.kind in ("int", "percent"):
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        if result.totals:
            total_row: list[Any] = [""] * len(result.columns)
            total_row[0] = "মোট"
            for index, column in enumerate(result.columns):
                if column.key in result.totals:
                    raw = result.totals[column.key]
                    if column.kind == "money":
                        total_row[index] = float(Decimal(int(raw)) / 100)
                    elif column.kind == "qty":
                        total_row[index] = float(Decimal(int(raw)) / 1000)
                    else:
                        total_row[index] = int(raw)
            sheet.append(total_row)
            current = sheet.max_row
            for index, column in enumerate(result.columns, start=1):
                cell = sheet.cell(row=current, column=index)
                cell.font = Font(name=bangla_font, bold=True, size=10)
                cell.fill = PatternFill("solid", fgColor="EEF2F7")
                cell.border = border
                if column.kind == "money":
                    cell.number_format = EXCEL_MONEY_FORMAT
                elif column.kind == "qty":
                    cell.number_format = EXCEL_QTY_FORMAT

        for index, column in enumerate(result.columns, start=1):
            longest = len(column.label)
            for row in result.rows[:200]:
                longest = max(longest, len(self.format_value(column, row.get(column.key))))
            sheet.column_dimensions[get_column_letter(index)].width = min(46, max(12, longest + 4))
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
        sheet.auto_filter.ref = (
            f"A{header_row}:{get_column_letter(len(result.columns))}{header_row + len(result.rows)}"
        )
        sheet.sheet_view.rightToLeft = False
        workbook.save(target)
        return target

    # -------------------------------------------------------------------- PDF
    def to_pdf(self, result: ReportResult, path: Path | str, *, landscape: bool | None = None) -> Path:
        """Render via Qt so Bengali shapes correctly and fonts are embedded."""
        from ..printing.documents import render_report_pdf

        target = self._target(result, path, "pdf")
        wide = landscape if landscape is not None else len(result.columns) > 6
        return render_report_pdf(
            result,
            target,
            business_name=self._business_name(),
            landscape=wide,
            format_value=self.format_value,
        )

    def export(self, result: ReportResult, path: Path | str, fmt: str) -> Path:
        fmt = fmt.lower().strip()
        if fmt == "csv":
            return self.to_csv(result, path)
        if fmt in ("xlsx", "excel"):
            return self.to_xlsx(result, path)
        if fmt == "pdf":
            return self.to_pdf(result, path)
        raise ValidationError("এক্সপোর্ট ফরম্যাট CSV, Excel বা PDF হতে হবে")
