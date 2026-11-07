#!/usr/bin/env python3
"""curve_widget.py : graphique en courbes (une série par joueur) pour l'interface Othello.

Dessiné à la main avec QPainter (aucune dépendance supplémentaire).
Abscisse = numéro du coup (ply) ; un clic sur le graphique émet plyClicked(ply).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


@dataclass
class Series:
    name: str
    line: QColor
    fill: QColor                      # remplissage des points
    edge: QColor                      # contour des points
    points: list[tuple[int, float]] = field(default_factory=list)   # (ply, valeur)
    # facultatif : (remplissage, contour) par point, aligné sur `points`
    dots: list[tuple[QColor, QColor]] | None = None
    # facultatif : entrées de légende (remplissage, contour, texte) remplaçant celle de la série
    legend: list[tuple[QColor, QColor, str]] | None = None


def _nice_axis(lo: float, hi: float, n: int = 4) -> tuple[float, float, list[float]]:
    """Bornes arrondies + graduations « rondes » couvrant [lo, hi]."""
    raw = max(hi - lo, 1e-9) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag + 1e-12)
    lo = math.floor(lo / step + 1e-9) * step
    hi = math.ceil(hi / step - 1e-9) * step
    ticks, v = [], lo
    while v <= hi + 1e-9:
        ticks.append(round(v, 10))
        v += step
    return lo, hi, ticks


class CurveChart(QWidget):
    PAD_X = 7           # marge intérieure pour que les points extrêmes ne soient pas coupés

    plyClicked = pyqtSignal(int)

    def __init__(self, unit: str = "", signed: bool = False, parent: QWidget | None = None) -> None:
        """signed=True : l'axe inclut 0 des deux côtés (scores) ; sinon il part de 0 (temps)."""
        super().__init__(parent)
        self.unit, self.signed = unit, signed
        self._series: list[Series] = []
        self._current = 0
        self._max_ply = 10
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, series: list[Series], current_ply: int, max_ply: int) -> None:
        self._series, self._current, self._max_ply = series, current_ply, max(max_ply, 10)
        self.update()

    # ---- géométrie --------------------------------------------------------

    def _plot(self) -> QRectF:
        return QRectF(46, 24, max(10, self.width() - 46 - 12), max(10, self.height() - 24 - 20))

    def _x(self, ply: float, plot: QRectF) -> float:
        inner = plot.width() - 2 * self.PAD_X
        return plot.left() + self.PAD_X + (ply - 1) / (self._max_ply - 1) * inner

    def _ply_at(self, x: float) -> int:
        plot = self._plot()
        inner = plot.width() - 2 * self.PAD_X
        return round((x - plot.left() - self.PAD_X) / inner * (self._max_ply - 1)) + 1

    # ---- dessin -----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(11)
        p.setFont(font)
        fm = p.fontMetrics()
        text = self.palette().color(QPalette.ColorRole.Text)
        grid = QColor(text)
        grid.setAlpha(45)
        plot = self._plot()

        # légende
        lx = plot.left()
        for s in self._series:
            for fill, edge, name in s.legend or [(s.fill, s.edge, s.name)]:
                p.setPen(QPen(edge, 1))
                p.setBrush(fill)
                p.drawEllipse(QPointF(lx + 4, 11), 4, 4)
                p.setPen(text)
                p.drawText(QPointF(lx + 13, 15), name)
                lx += 13 + fm.horizontalAdvance(name) + 16

        values = [v for s in self._series for _, v in s.points]
        if not values:
            p.setPen(QColor(text.red(), text.green(), text.blue(), 130))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Aucune donnée pour cette partie")
            return

        lo, hi = min(values), max(values)
        if self.signed:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        else:
            lo = 0.0
        lo, hi, yticks = _nice_axis(lo, hi)
        if hi == lo:
            hi = lo + 1

        def y(v: float) -> float:
            return plot.bottom() - (v - lo) / (hi - lo) * plot.height()

        # grille + graduations Y
        for v in yticks:
            zero = self.signed and abs(v) < 1e-9
            p.setPen(QPen(text if zero else grid, 1))
            p.drawLine(QPointF(plot.left(), y(v)), QPointF(plot.right(), y(v)))
            label = ("0" if zero else f"{v:+g}") if self.signed else f"{v:g}{self.unit}"
            p.setPen(text)
            p.drawText(QRectF(0, y(v) - 8, plot.left() - 5, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        # graduations X
        for k in range(10, self._max_ply + 1, 10):
            xk = self._x(k, plot)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(xk, plot.top()), QPointF(xk, plot.bottom()))
            p.setPen(text)
            p.drawText(QRectF(xk - 15, plot.bottom() + 3, 30, 14), Qt.AlignmentFlag.AlignCenter, str(k))

        # position courante
        if 1 <= self._current <= self._max_ply:
            hl = self.palette().color(QPalette.ColorRole.Highlight)
            p.setPen(QPen(hl, 1.5))
            xc = self._x(self._current, plot)
            p.drawLine(QPointF(xc, plot.top()), QPointF(xc, plot.bottom()))

        # courbes
        for s in self._series:
            if len(s.points) > 1:
                path = QPainterPath(QPointF(self._x(s.points[0][0], plot), y(s.points[0][1])))
                for ply, v in s.points[1:]:
                    path.lineTo(self._x(ply, plot), y(v))
                p.setPen(QPen(s.line, 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            for i, (ply, v) in enumerate(s.points):
                fill, edge = s.dots[i] if s.dots else (s.fill, s.edge)
                p.setPen(QPen(edge, 1))
                p.setBrush(fill)
                p.drawEllipse(QPointF(self._x(ply, plot), y(v)), 3, 3)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._plot().contains(event.position()):
            ply = self._ply_at(event.position().x())
            if 1 <= ply <= self._max_ply:
                self.plyClicked.emit(ply)
