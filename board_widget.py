#!/usr/bin/env python3
"""board_widget.py : widget PyQt6 qui dessine le plateau d'Othello."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QPainter, QPalette, QPen,
                         QRadialGradient)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from othello_board import BLACK, SQUARES, WHITE, Game


class BoardWidget(QWidget):
    """Dessine la position de `game.board` et émet moveClicked(case)."""

    moveClicked = pyqtSignal(int)
    MARGIN = 0.55

    def __init__(self, game: Game, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game = game
        self.show_hints = True
        self.interactive = True
        self.last_move: int | None = None
        self._hover: int | None = None
        self.setMinimumSize(380, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(580, 580)

    def _layout(self) -> tuple[float, float, float]:
        side = min(self.width(), self.height())
        cell = side / (8 + 2 * self.MARGIN)
        ox = (self.width() - side) / 2 + cell * self.MARGIN
        oy = (self.height() - side) / 2 + cell * self.MARGIN
        return cell, ox, oy

    def _square_at(self, pos: QPointF) -> int | None:
        cell, ox, oy = self._layout()
        c = int((pos.x() - ox) // cell)
        r = int((pos.y() - oy) // cell)
        return (r + 1) * 9 + c + 1 if 0 <= c < 8 and 0 <= r < 8 else None

    @staticmethod
    def _cell_origin(x: int, cell: float, ox: float, oy: float) -> QPointF:
        return QPointF(ox + (x % 9 - 1) * cell, oy + (x // 9 - 1) * cell)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell, ox, oy = self._layout()
        board = self.game.board
        no_pen = Qt.PenStyle.NoPen

        # cadre + tapis
        pad = cell * 0.12
        p.setPen(no_pen)
        p.setBrush(QColor("#4e342e"))
        p.drawRoundedRect(QRectF(ox - pad, oy - pad, 8 * cell + 2 * pad, 8 * cell + 2 * pad), 6, 6)
        p.setBrush(QColor("#2e7d32"))
        p.drawRect(QRectF(ox, oy, 8 * cell, 8 * cell))

        # grille et repères
        p.setPen(QPen(QColor("#1b5e20"), max(1.0, cell * 0.025)))
        for i in range(9):
            p.drawLine(QPointF(ox + i * cell, oy), QPointF(ox + i * cell, oy + 8 * cell))
            p.drawLine(QPointF(ox, oy + i * cell), QPointF(ox + 8 * cell, oy + i * cell))
        p.setPen(no_pen)
        p.setBrush(QColor("#1b5e20"))
        for gx in (2, 6):
            for gy in (2, 6):
                p.drawEllipse(QPointF(ox + gx * cell, oy + gy * cell), cell * 0.06, cell * 0.06)

        # coordonnées
        font = QFont(self.font())
        font.setPixelSize(max(9, int(cell * 0.28)))
        p.setFont(font)
        p.setPen(self.palette().color(QPalette.ColorRole.Text))
        m = cell * self.MARGIN
        centered = Qt.AlignmentFlag.AlignCenter
        for i in range(8):
            letter, digit = "ABCDEFGH"[i], str(i + 1)
            p.drawText(QRectF(ox + i * cell, oy - m, cell, m), centered, letter)
            p.drawText(QRectF(ox - m, oy + i * cell, m, cell), centered, digit)

        # survol
        legal = board.legal_moves() if self.interactive else []
        if self.show_hints and self._hover in legal:
            o = self._cell_origin(self._hover, cell, ox, oy)
            p.setPen(no_pen)
            p.setBrush(QColor(255, 255, 255, 45))
            p.drawRect(QRectF(o.x(), o.y(), cell, cell))

        # pions
        rad = cell * 0.43
        for x in SQUARES:
            v = board.square[x]
            if v > WHITE:
                continue
            o = self._cell_origin(x, cell, ox, oy)
            c = QPointF(o.x() + cell / 2, o.y() + cell / 2)
            g = QRadialGradient(c + QPointF(-rad * 0.35, -rad * 0.35), rad * 1.5)
            if v == BLACK:
                g.setColorAt(0, QColor("#5a5a5a"))
                g.setColorAt(1, QColor("#050505"))
            else:
                g.setColorAt(0, QColor("#ffffff"))
                g.setColorAt(1, QColor("#b8b8b8"))
            p.setBrush(QBrush(g))
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawEllipse(c, rad, rad)

        # aides : coups légaux
        if self.show_hints:
            hint = QColor(0, 0, 0, 110) if board.player == BLACK else QColor(255, 255, 255, 160)
            p.setPen(no_pen)
            p.setBrush(hint)
            for x in legal:
                o = self._cell_origin(x, cell, ox, oy)
                p.drawEllipse(QPointF(o.x() + cell / 2, o.y() + cell / 2), cell * 0.11, cell * 0.11)

        # dernier coup
        if self.last_move is not None:
            o = self._cell_origin(self.last_move, cell, ox, oy)
            p.setPen(no_pen)
            p.setBrush(QColor("#e53935"))
            p.drawEllipse(QPointF(o.x() + cell / 2, o.y() + cell / 2), cell * 0.08, cell * 0.08)

    def mouseMoveEvent(self, event) -> None:
        sq = self._square_at(event.position())
        if sq != self._hover:
            self._hover = sq
            self.update()
        playable = (self.interactive and sq is not None and self.game.board.is_legal(sq))
        self.setCursor(Qt.CursorShape.PointingHandCursor if playable
                       else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, _event) -> None:
        self._hover = None
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.interactive:
            return
        sq = self._square_at(event.position())
        if sq is not None and self.game.board.is_legal(sq):
            self.moveClicked.emit(sq)


# --------------------------------------------------------------------------
# Arbre d'historique : la flèche haute remonte au parent