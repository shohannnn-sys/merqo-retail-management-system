"""Qt document rendering: report PDFs, thermal receipts and barcode labels.

Bengali is shaped by Qt's text engine using a bundled Noto Sans Bengali (SIL OFL),
so PDFs, previews and paper output are identical. A raster path is provided for
printer drivers that mangle Unicode text.

Qt is imported inside functions so the headless business core and its tests never
require a GUI stack.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.money import format_money
from ..core.quantity import format_quantity

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_fonts_loaded = False


def load_fonts() -> list[str]:
    """Register bundled fonts with Qt. Safe to call repeatedly."""
    global _fonts_loaded
    from PySide6.QtGui import QFontDatabase

    if _fonts_loaded:
        return []
    families: list[str] = []
    for path in sorted(FONT_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    _fonts_loaded = True
    return families


def _ensure_app() -> Any:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    load_fonts()
    return app


def _printer(
    output_path: Path,
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    margin_mm: float = 8.0,
    landscape: bool = False,
) -> Any:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output_path))
    printer.setFullPage(False)
    if width_mm is not None:
        size = QPageSize(QSizeF(width_mm, height_mm or 297.0), QPageSize.Millimeter)
    else:
        size = QPageSize(QPageSize.A4)
    layout = QPageLayout(
        size,
        QPageLayout.Landscape if landscape else QPageLayout.Portrait,
        QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm),
        QPageLayout.Millimeter,
    )
    printer.setPageLayout(layout)
    return printer


def render_html_pdf(
    html_text: str,
    output_path: Path | str,
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    margin_mm: float = 8.0,
    landscape: bool = False,
) -> Path:
    from PySide6.QtGui import QTextDocument

    _ensure_app()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = QTextDocument()
    document.setHtml(html_text)
    printer = _printer(
        target, width_mm=width_mm, height_mm=height_mm, margin_mm=margin_mm, landscape=landscape
    )
    document.print_(printer)
    return target


def render_report_pdf(
    result: Any,
    output_path: Path | str,
    *,
    business_name: str = "",
    landscape: bool = False,
    format_value: Callable[[Any, Any], str] | None = None,
) -> Path:
    """Render a ReportResult as a paginated A4 PDF with an embedded Bangla font."""
    fmt = format_value or (lambda column, value: "" if value is None else str(value))
    filters = result.meta.get("filters", {})
    period = ""
    if filters.get("start"):
        period = f"{filters['start']} — {filters.get('end', '')}"
    escape = html.escape
    head = "".join(f"<th>{escape(c.label)}</th>" for c in result.columns)
    body_rows = []
    for row in result.rows:
        cells = []
        for column in result.columns:
            align = "right" if column.kind in ("money", "qty", "int", "percent") else "left"
            cells.append(f'<td align="{align}">{escape(fmt(column, row.get(column.key)))}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    total_cells = []
    for index, column in enumerate(result.columns):
        if index == 0:
            total_cells.append('<td align="left"><b>মোট</b></td>')
        elif column.key in result.totals:
            total_cells.append(
                f'<td align="right"><b>{escape(fmt(column, result.totals[column.key]))}</b></td>'
            )
        else:
            total_cells.append("<td></td>")
    totals_row = f'<tr class="total">{"".join(total_cells)}</tr>' if result.totals else ""

    html_text = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
      body {{ font-family: 'Noto Sans Bengali','Nirmala UI',sans-serif; font-size: 9pt; color:#1B2430; }}
      h1 {{ font-size: 15pt; margin:0 0 2pt 0; }}
      h2 {{ font-size: 11pt; margin:0 0 2pt 0; font-weight:600; color:#33415C; }}
      .meta {{ font-size: 8pt; color:#5A6472; margin-bottom:8pt; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th {{ background:#1F3A5F; color:#FFFFFF; padding:4pt 5pt; font-size:8.5pt; text-align:left; }}
      td {{ padding:3pt 5pt; border-bottom:0.5pt solid #DDE3EA; font-size:8.5pt; }}
      tr.total td {{ background:#EEF2F7; border-top:1pt solid #1F3A5F; }}
    </style></head><body>
      <h1>{escape(business_name or result.title)}</h1>
      <h2>{escape(result.title)}</h2>
      <div class="meta">সময়কাল: {escape(period)} &nbsp;|&nbsp; রেকর্ড: {len(result.rows)}
        &nbsp;|&nbsp; তৈরি: {datetime.now().strftime("%d/%m/%Y %I:%M %p")}</div>
      <table><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}{totals_row}</tbody></table>
    </body></html>"""
    return render_html_pdf(html_text, output_path, landscape=landscape, margin_mm=10.0)


# --------------------------------------------------------------------- receipts
def receipt_html(
    sale: dict[str, Any],
    business: Any,
    settings: Any,
    *,
    width_mm: float = 80.0,
    copy_label: str = "",
) -> str:
    """Build a thermal receipt at an exact paper width. No software branding."""
    escape = html.escape
    symbol = settings.get("currency_symbol", "৳")
    font_size = settings.get_int("receipt_font_size", 9)
    show_logo = settings.get_bool("receipt_show_logo", True)
    money = lambda v: format_money(int(v), symbol="", grouping=True)  # noqa: E731
    precision = 3

    logo_html = ""
    if show_logo and business.logo_path:
        logo = Path(business.logo_path)
        if logo.is_file():
            logo_html = f'<div align="center"><img src="{logo.as_uri()}" width="110"></div>'

    item_rows = []
    for item in sale.get("items", []):
        name = escape(str(item["product_name"]))
        qty = format_quantity(int(item["quantity"]), precision=precision)
        unit = escape(str(item.get("unit_name") or ""))
        price = money(item["unit_price"])
        total = money(item["net_amount"])
        discount = int(item["discount_amount"]) + int(item["invoice_discount_allocated"])
        discount_line = ""
        if discount:
            discount_line = f'<tr><td colspan="3" class="sub">ডিস্কাউন্ট: -{money(discount)}</td></tr>'
        item_rows.append(
            f'<tr><td colspan="3" class="pname">{name}</td></tr>'
            f'<tr><td class="sub">{qty} {unit} × {price}</td>'
            f'<td></td><td align="right">{total}</td></tr>{discount_line}'
        )

    payment_rows = "".join(
        f'<tr><td colspan="2">{escape(str(p["method_name"]))}</td>'
        f'<td align="right">{money(p["amount"])}</td></tr>'
        for p in sale.get("payments", [])
    )
    customer = sale.get("customer_name") or "ওয়াক-ইন কাস্টমার"
    due = int(sale.get("due_amount", 0))
    footer = escape(business.receipt_footer or "ধন্যবাদ — আবার আসবেন")
    tax_row = ""
    if int(sale.get("tax_amount", 0)):
        tax_row = (
            f'<tr><td colspan="2">{escape(settings.get("tax_label", "ভ্যাট"))}</td>'
            f'<td align="right">{money(sale["tax_amount"])}</td></tr>'
        )
    discount_row = ""
    total_discount = int(sale.get("item_discount", 0)) + int(sale.get("invoice_discount", 0))
    if total_discount:
        discount_row = (
            f'<tr><td colspan="2">মোট ডিস্কাউন্ট</td><td align="right">-{money(total_discount)}</td></tr>'
        )
    status_note = ""
    if sale.get("status") == "cancelled":
        status_note = '<div align="center" class="warn">** বাতিলকৃত ইনভয়েস **</div>'
    elif sale.get("status") in ("partially_returned", "returned"):
        status_note = '<div align="center" class="warn">** রিটার্ন হয়েছে **</div>'

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
      body {{ font-family:'Noto Sans Bengali','Nirmala UI',sans-serif;
              font-size:{font_size}pt; color:#000; margin:0; }}
      table {{ width:100%; border-collapse:collapse; }}
      td {{ padding:0.6pt 0; vertical-align:top; }}
      .center {{ text-align:center; }}
      .bname {{ font-size:{font_size + 4}pt; font-weight:700; }}
      .sub {{ font-size:{max(6, font_size - 1)}pt; }}
      .pname {{ font-weight:600; padding-top:2pt; }}
      .rule {{ border-top:0.6pt dashed #000; margin:3pt 0; }}
      .grand {{ font-size:{font_size + 2}pt; font-weight:700; }}
      .warn {{ font-weight:700; margin-top:3pt; }}
    </style></head><body>
      {logo_html}
      <div class="center bname">{escape(business.name or "")}</div>
      <div class="center sub">{escape(business.address or "")}</div>
      <div class="center sub">মোবাইল: {escape(business.phone or "")}</div>
      {f'<div class="center sub">ভ্যাট নং: {escape(business.tax_number)}</div>' if business.tax_number else ""}
      <div class="rule"></div>
      <table>
        <tr><td colspan="2">ইনভয়েস: {escape(str(sale.get("invoice_no", "")))}</td>
            <td align="right">{escape(str(sale.get("sale_date", "")))}</td></tr>
        <tr><td colspan="3">কাস্টমার: {escape(str(customer))}</td></tr>
      </table>
      <div class="rule"></div>
      <table>{"".join(item_rows)}</table>
      <div class="rule"></div>
      <table>
        <tr><td colspan="2">সাবটোটাল</td><td align="right">{money(sale.get("subtotal", 0))}</td></tr>
        {discount_row}{tax_row}
        <tr class="grand"><td colspan="2">সর্বমোট</td>
            <td align="right">{symbol} {money(sale.get("grand_total", 0))}</td></tr>
        {payment_rows}
        <tr><td colspan="2">পরিশোধিত</td><td align="right">{money(sale.get("paid_amount", 0))}</td></tr>
        <tr class="grand"><td colspan="2">বাকি</td><td align="right">{money(due)}</td></tr>
      </table>
      <div class="rule"></div>
      {status_note}
      <div class="center sub">{footer}</div>
      {f'<div class="center sub">{escape(copy_label)}</div>' if copy_label else ""}
      <div class="center sub">{escape(str(sale.get("sale_time", "")))}</div>
    </body></html>"""


def render_receipt_pdf(
    sale: dict[str, Any],
    business: Any,
    settings: Any,
    output_path: Path | str,
    *,
    width_mm: float | None = None,
) -> Path:
    width = width_mm or float(settings.get("paper_width_mm", "80"))
    margin = float(settings.get_int("receipt_margin_mm", 3))
    html_text = receipt_html(sale, business, settings, width_mm=width)
    return render_html_pdf(html_text, output_path, width_mm=width, height_mm=297.0, margin_mm=margin)


def render_receipt_image(
    sale: dict[str, Any],
    business: Any,
    settings: Any,
    output_path: Path | str,
    *,
    width_mm: float | None = None,
    dpi: int = 203,
) -> Path:
    """Raster fallback for printer drivers that cannot shape Unicode text."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QPainter, QTextDocument

    _ensure_app()
    width = width_mm or float(settings.get("paper_width_mm", "80"))
    margin = float(settings.get_int("receipt_margin_mm", 3))
    usable_mm = max(10.0, width - 2 * margin)
    pixel_width = int(usable_mm / 25.4 * dpi)
    document = QTextDocument()
    document.setHtml(receipt_html(sale, business, settings, width_mm=width))
    document.setTextWidth(pixel_width)
    size = document.size().toSize()
    image = QImage(QSize(pixel_width, max(1, size.height())), QImage.Format_Mono)
    image.fill(Qt.white)
    painter = QPainter(image)
    document.drawContents(painter)
    painter.end()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(target), "PNG")
    return target


def available_printers() -> list[str]:
    from PySide6.QtPrintSupport import QPrinterInfo

    _ensure_app()
    return [p.printerName() for p in QPrinterInfo.availablePrinters()]


def default_printer_name() -> str:
    from PySide6.QtPrintSupport import QPrinterInfo

    _ensure_app()
    return QPrinterInfo.defaultPrinter().printerName()


def print_html(
    html_text: str,
    *,
    printer_name: str = "",
    width_mm: float | None = None,
    margin_mm: float = 3.0,
    copies: int = 1,
) -> bool:
    """Send a document to a physical Windows printer."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
    from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

    _ensure_app()
    if printer_name:
        info = QPrinterInfo.printerInfo(printer_name)
        if info.isNull():
            raise RuntimeError(f"প্রিন্টার খুঁজে পাওয়া যায়নি: {printer_name}")
        printer = QPrinter(info, QPrinter.HighResolution)
    else:
        printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.NativeFormat)
    printer.setCopyCount(max(1, copies))
    if width_mm:
        layout = QPageLayout(
            QPageSize(QSizeF(width_mm, 297.0), QPageSize.Millimeter),
            QPageLayout.Portrait,
            QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm),
            QPageLayout.Millimeter,
        )
        printer.setPageLayout(layout)
    document = QTextDocument()
    document.setHtml(html_text)
    document.print_(printer)
    return True


def barcode_image(code: str, *, symbology: str = "code128", height: float = 15.0) -> Any:
    """Return a QImage of a barcode (Code128 by default)."""
    import io

    import barcode
    from barcode.writer import ImageWriter
    from PySide6.QtGui import QImage

    _ensure_app()
    buffer = io.BytesIO()
    barcode.get(symbology, code, writer=ImageWriter()).write(
        buffer, options={"module_height": height, "write_text": True, "font_size": 8}
    )
    image = QImage()
    image.loadFromData(buffer.getvalue())
    return image


def qr_image(text: str, *, box_size: int = 6) -> Any:
    import io

    import qrcode
    from PySide6.QtGui import QImage

    _ensure_app()
    qr = qrcode.QRCode(box_size=box_size, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    image = QImage()
    image.loadFromData(buffer.getvalue())
    return image


def label_html(
    product: dict[str, Any],
    business_name: str,
    *,
    width_mm: float = 50.0,
    height_mm: float = 25.0,
    show_price: bool = True,
) -> str:
    escape = html.escape
    price = format_money(int(product.get("selling_price", 0)))
    image = barcode_image(str(product.get("barcode") or product.get("sku", "")))
    import base64

    from PySide6.QtCore import QBuffer, QByteArray

    array = QByteArray()
    buffer = QBuffer(array)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    encoded = base64.b64encode(bytes(array)).decode("ascii")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
      body {{ font-family:'Noto Sans Bengali',sans-serif; font-size:7pt; margin:0; text-align:center; }}
      .name {{ font-weight:600; font-size:8pt; }}
      .price {{ font-size:10pt; font-weight:700; }}
    </style></head><body>
      <div class="name">{escape(business_name)}</div>
      <div class="name">{escape(str(product.get("name", "")))}</div>
      <img src="data:image/png;base64,{encoded}" width="{int(width_mm * 3)}">
      {f'<div class="price">৳ {price}</div>' if show_price else ""}
    </body></html>"""
