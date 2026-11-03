"""Lightweight chart widgets painted with QPainter (no external chart dependency)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.money import format_money
from .theme import COLORS


class ChartWidget(QWidget):
    """Bar or line chart driven by real query results."""

    def __init__(self, title: str = "", kind: str = "bar", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._kind = kind
        self._points: list[tuple[str, float]] = []
        self._series2: list[float] = []
        self._money = True
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(
        self,
        points: Sequence[tuple[str, float]],
        second: Sequence[float] | None = None,
        *,
        money: bool = True,
    ) -> None:
        self._points = [(str(label), float(value)) for label, value in points]
        self._series2 = [float(v) for v in second] if second else []
        self._money = money
        self.update()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(self.rect(), QColor(COLORS["surface"]))

        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSize(10)
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, self._title
        )
        plot = QRectF(rect.left() + 4, rect.top() + 26, rect.width() - 8, rect.height() - 52)

        if not self._points:
            painter.setPen(QColor(COLORS["text_subtle"]))
            body = QFont(self.font())
            body.setPointSize(9)
            painter.setFont(body)
            painter.drawText(plot, Qt.AlignCenter, "এই সময়কালে কোনো তথ্য নেই")
            painter.end()
            return

        values = [v for _, v in self._points] + self._series2
        maximum = max(values) if values else 0
        minimum = min(0.0, min(values)) if values else 0
        span = (maximum - minimum) or 1.0

        grid_pen = QPen(QColor(COLORS["border"]))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for step in range(5):
            y = plot.top() + plot.height() * step / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        body = QFont(self.font())
        body.setPointSize(7)
        painter.setFont(body)
        painter.setPen(QColor(COLORS["text_subtle"]))
        for step in range(5):
            value = maximum - span * step / 4
            y = plot.top() + plot.height() * step / 4
            label = format_money(int(value), decimals=0) if self._money else f"{value:,.0f}"
            painter.drawText(QRectF(plot.left(), y - 8, 70, 14), Qt.AlignLeft | Qt.AlignVCenter, label)

        count = len(self._points)
        slot = plot.width() / max(1, count)
        if self._kind == "bar":
            bar_width = max(3.0, min(28.0, slot * 0.55))
            painter.setPen(Qt.NoPen)
            for index, (_, value) in enumerate(self._points):
                height = (value - minimum) / span * plot.height()
                x = plot.left() + slot * index + (slot - bar_width) / 2
                y = plot.bottom() - height
                painter.setBrush(QColor(COLORS["primary"]))
                painter.drawRoundedRect(QRectF(x, y, bar_width, max(1.0, height)), 3, 3)
        else:
            path = QPainterPath()
            for index, (_, value) in enumerate(self._points):
                x = plot.left() + slot * index + slot / 2
                y = plot.bottom() - (value - minimum) / span * plot.height()
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            pen = QPen(QColor(COLORS["primary"]))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setBrush(QColor(COLORS["primary"]))
            painter.setPen(Qt.NoPen)
            for index, (_, value) in enumerate(self._points):
                x = plot.left() + slot * index + slot / 2
                y = plot.bottom() - (value - minimum) / span * plot.height()
                painter.drawEllipse(QPointF(x, y), 3, 3)
            if self._series2:
                path2 = QPainterPath()
                for index, value in enumerate(self._series2[:count]):
                    x = plot.left() + slot * index + slot / 2
                    y = plot.bottom() - (value - minimum) / span * plot.height()
                    if index == 0:
                        path2.moveTo(x, y)
                    else:
                        path2.lineTo(x, y)
                pen2 = QPen(QColor(COLORS["accent"]))
                pen2.setWidth(2)
                pen2.setStyle(Qt.DashLine)
                painter.setPen(pen2)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path2)

        painter.setPen(QColor(COLORS["text_muted"]))
        stride = max(1, count // 6)
        for index, (label, _) in enumerate(self._points):
            if index % stride:
                continue
            x = plot.left() + slot * index
            short = label[5:] if len(label) >= 10 else label
            painter.drawText(QRectF(x, plot.bottom() + 4, slot, 16), Qt.AlignCenter, short)
        painter.end()


class DonutWidget(QWidget):
    """Category share chart used for expense and payment breakdowns."""

    PALETTE = ["#1F3A5F", "#0E7C66", "#B45309", "#1D4ED8", "#7C3AED", "#0891B2", "#BE123C"]

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._slices: list[tuple[str, float]] = []
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, slices: Sequence[tuple[str, float]]) -> None:
        self._slices = [(str(k), float(v)) for k, v in slices if v]
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["surface"]))
        rect = self.rect().adjusted(12, 12, -12, -12)
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSize(10)
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, self._title
        )
        if not self._slices:
            painter.setPen(QColor(COLORS["text_subtle"]))
            painter.drawText(rect, Qt.AlignCenter, "কোনো তথ্য নেই")
            painter.end()
            return
        diameter = min(rect.height() - 34, rect.width() * 0.45)
        circle = QRectF(rect.left() + 6, rect.top() + 30, diameter, diameter)
        total = sum(v for _, v in self._slices) or 1.0
        start = 90 * 16
        for index, (_, value) in enumerate(self._slices):
            span = int(-value / total * 360 * 16)
            painter.setBrush(QColor(self.PALETTE[index % len(self.PALETTE)]))
            painter.setPen(Qt.NoPen)
            painter.drawPie(circle, start, span)
            start += span
        inner = circle.adjusted(diameter * 0.28, diameter * 0.28, -diameter * 0.28, -diameter * 0.28)
        painter.setBrush(QColor(COLORS["surface"]))
        painter.drawEllipse(inner)

        body = QFont(self.font())
        body.setPointSize(8)
        painter.setFont(body)
        legend_x = circle.right() + 16
        y = circle.top() + 4
        for index, (label, value) in enumerate(self._slices[:7]):
            painter.setBrush(QColor(self.PALETTE[index % len(self.PALETTE)]))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(legend_x, y + 3, 9, 9))
            painter.setPen(QColor(COLORS["text"]))
            share = value / total * 100
            text = f"{label[:18]}  {share:.0f}%"
            painter.drawText(
                QRectF(legend_x + 15, y, rect.right() - legend_x - 15, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                text,
            )
            y += 20
        painter.end()
