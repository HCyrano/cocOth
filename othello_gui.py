#!/usr/bin/env python3
"""othello_gui.py : interface PyQt6 pour jouer avec othello_board.

- Arbre d'historique avec gestion des variantes (voir history_tree.py).
- Plateau dessiné par board_widget.py.
"""

from __future__ import annotations

import random
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFontDatabase, QKeySequence, QPalette
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                             QFrame, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMainWindow, QMessageBox, QTabWidget,
                             QVBoxLayout, QWidget)

from board_widget import BoardWidget
from curve_widget import CurveChart, Series
from history_tree import GameNode, HistoryTreeController, load_tree, save_tree
from ggf import (describe_type, fmt_clock, parse_ggf, parse_time_control,
                 to_ggf)
from othello_board import BLACK, PASS, WHITE, Board, Game


class MainWindow(QMainWindow):
    AI_DELAY_MS = 350
    NAMES = {BLACK: "Noir", WHITE: "Blanc"}
    KINDS = ("Humain", "Aléatoire", "Glouton")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CocOth")

        self.game = Game()
        self.root_node = GameNode(None, self.game.board)
        self.current_node = self.root_node
        self._notice = ""

        self.board_view = BoardWidget(self.game)
        self.board_view.moveClicked.connect(self._on_click)

        self._ai_timer = QTimer(self)
        self._ai_timer.setSingleShot(True)
        self._ai_timer.timeout.connect(self._ai_move)

        # Table « Partie » : une ligne par joueur (nom, type, nombre de pions)
        self.kind = {BLACK: QComboBox(), WHITE: QComboBox()}
        for combo in self.kind.values():
            combo.addItems(self.KINDS)

        self._style_cache: dict[QWidget, str] = {}
        self.glyph_label: dict[int, QLabel] = {}
        self.name_edit: dict[int, QLineEdit] = {}
        self.disc_label: dict[int, QLabel] = {}
        self.clock_label: dict[int, QLabel] = {}

        self.player_frame: dict[int, QFrame] = {}

        game_box = QGroupBox("Partie")
        game_lay = QVBoxLayout(game_box)
        for color, glyph in ((BLACK, "●"), (WHITE, "○")):
            frame = QFrame()
            frame.setObjectName("playerFrame")
            self.player_frame[color] = frame
            card = QVBoxLayout(frame)
            card.setContentsMargins(8, 6, 8, 6)
            card.setSpacing(2)

            self.glyph_label[color] = QLabel(glyph)
            edit = QLineEdit(self.NAMES[color])
            edit.setMaxLength(20)
            edit.setToolTip("Cliquer pour renommer le joueur")
            # Pas de focus au clavier : les raccourcis Ctrl+C / Ctrl+V restent ceux des menus.
            edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            edit.returnPressed.connect(edit.clearFocus)
            edit.textChanged.connect(lambda _text: self._refresh())
            self.name_edit[color] = edit
            top = QHBoxLayout()
            top.addWidget(self.glyph_label[color])
            top.addWidget(edit, 1)
            top.addWidget(self.kind[color])
            card.addLayout(top)

            self.disc_label[color] = QLabel()
            self.disc_label[color].setMinimumWidth(30)
            self.disc_label[color].setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            caption = QLabel("pions")
            caption.setStyleSheet("font-size: 11px; color: gray;")
            self.clock_label[color] = QLabel()
            self.clock_label[color].setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.clock_label[color].setMinimumWidth(56)
            bottom = QHBoxLayout()
            bottom.addWidget(self.disc_label[color])
            bottom.addWidget(caption)
            bottom.addStretch(1)
            bottom.addWidget(self.clock_label[color])
            card.addLayout(bottom)
            game_lay.addWidget(frame)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("font-size: 11px; color: gray;")
        game_lay.addWidget(self.info)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(48)
        self.status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        game_lay.addWidget(self.status)

        # Arbre d'historique
        self.history = HistoryTreeController(
            get_current_node=lambda: self.current_node,
            set_current_node=self._set_current_node,
            sync_game=self._sync_game_to_current_node,
            kick=self._kick,
        )
        self.tree_widget = self.history.widget
        self.tree_widget.setHeaderLabels(["Historique & Variantes"])
        self.tree_widget.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        history_box = QGroupBox("Arbre d'historique")
        QVBoxLayout(history_box).addWidget(self.tree_widget)

        side = QVBoxLayout()
        side.addWidget(game_box)
        side.addWidget(history_box, 1)
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(380)

        # Onglets sous l'othellier : courbes des scores et des temps
        self.score_chart = CurveChart(signed=True)
        self.time_chart = CurveChart(unit="s")
        self.cum_check = QCheckBox("Cumulé")
        self.cum_check.toggled.connect(lambda _on: self._refresh_charts())
        self.black_pov_check = QCheckBox("Point de vue de Noir (+ = avantage Noir)")
        self.black_pov_check.toggled.connect(lambda _on: self._refresh_charts())
        score_tab = QWidget()
        sl = QVBoxLayout(score_tab)
        sl.setContentsMargins(4, 2, 4, 2)
        sl.addWidget(self.black_pov_check, 0, Qt.AlignmentFlag.AlignRight)
        sl.addWidget(self.score_chart, 1)
        time_tab = QWidget()
        tl = QVBoxLayout(time_tab)
        tl.setContentsMargins(4, 2, 4, 2)
        tl.addWidget(self.cum_check, 0, Qt.AlignmentFlag.AlignRight)
        tl.addWidget(self.time_chart, 1)
        self.charts = QTabWidget()
        self.charts.addTab(score_tab, "Scores")
        self.charts.addTab(time_tab, "Temps")
        self.charts.setFixedHeight(200)
        self.score_chart.plyClicked.connect(self._goto_ply)
        self.time_chart.plyClicked.connect(self._goto_ply)

        left = QVBoxLayout()
        left.addWidget(self.board_view, 1)
        left.addWidget(self.charts)

        root = QHBoxLayout()
        root.addLayout(left, 1)
        root.addWidget(panel)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(1030, 840)

        self._build_menus()

        for combo in self.kind.values():
            combo.currentIndexChanged.connect(self._kick)
        self.history.rebuild(self.root_node, self.current_node)
        self._after_move()

    # ---- menus ------------------------------------------------------------

    def _build_menus(self) -> None:
        SK = QKeySequence.StandardKey

        def action(text: str, slot, shortcut=None, checkable: bool = False) -> QAction:
            act = QAction(text, self)
            if shortcut is not None:
                act.setShortcut(QKeySequence(shortcut))
            if checkable:
                act.setCheckable(True)
                act.toggled.connect(slot)
            else:
                act.triggered.connect(lambda _checked=False: slot())
            return act

        bar = self.menuBar()

        file_menu = bar.addMenu("&Fichier")
        self.act_new = action("&Nouvelle partie", self._new_game, SK.New)
        self.act_open = action("&Ouvrir un arbre…", self._open_tree, SK.Open)
        self.act_save = action("&Enregistrer l'arbre…", self._save_tree, SK.Save)
        self.act_quit = action("&Quitter", self.close, SK.Quit)
        file_menu.addAction(self.act_new)
        file_menu.addSeparator()
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_save)
        file_menu.addSeparator()
        self.act_import_ggf = action("&Importer une partie GGF…", self._import_ggf)
        self.act_export_ggf = action("E&xporter la partie en GGF…", self._export_ggf)
        file_menu.addAction(self.act_import_ggf)
        file_menu.addAction(self.act_export_ggf)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = bar.addMenu("&Édition")
        self.act_copy = action("&Copier le transcript", self._copy_transcript, SK.Copy)
        self.act_paste = action("C&oller un transcript", self._paste_transcript, SK.Paste)
        self.act_delete = action("&Supprimer le coup (et ses variantes)",
                                 self._delete_current, SK.Delete)
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_delete)

        view_menu = bar.addMenu("&Affichage")
        self.act_hints = action("Afficher les coups &légaux", self._on_hints, checkable=True)
        self.act_hints.setChecked(True)
        view_menu.addAction(self.act_hints)

    def _new_game(self) -> None:
        self.game = Game()
        self.root_node = GameNode(None, self.game.board)
        self.current_node = self.root_node
        self.board_view.game = self.game
        self.history.rebuild(self.root_node, self.current_node)
        self._after_move()

    def _sync_game_to_current_node(self) -> None:
        """Met à jour l'objet Game pour qu'il corresponde au nœud courant de l'arbre."""
        path = []
        node = self.current_node
        while node.parent is not None:
            path.append(node.move)
            node = node.parent
        path.reverse()

        g = Game(node.board)    # node = racine : position de départ (peut être non standard)
        for m in path:
            if g.board.must_pass() and not g.board.is_legal(m) and m != PASS:
                g.play(PASS)
            g.play(m)
        self.game = g
        self.board_view.game = g

    def _set_current_node(self, node: GameNode) -> None:
        self.current_node = node

    def _name(self, player: int) -> str:
        """Nom affiché du joueur (nom par défaut si le champ est vide)."""
        return self.name_edit[player].text().strip() or self.NAMES[player]

    def _set_style(self, widget: QWidget, css: str) -> None:
        """setStyleSheet seulement si la feuille change (évite de repolir à chaque rafraîchissement)."""
        if self._style_cache.get(widget) != css:
            self._style_cache[widget] = css
            widget.setStyleSheet(css)

    def _is_ai(self, player: int) -> bool:
        return self.kind[player].currentIndex() != 0

    def _after_move(self, notice: str = "") -> None:
        g = self.game
        self._notice = notice
        if not g.is_over() and g.board.must_pass():
            self._notice = f"{self._name(g.player)} n'a aucun coup : il passe."
            self.play_move(PASS)
            return
        self._kick()

    def _kick(self) -> None:
        self._ai_timer.stop()
        g = self.game
        if not g.is_over() and self._is_ai(g.player):
            self._ai_timer.start(self.AI_DELAY_MS)
        self._refresh()

    def play_move(self, move: int) -> None:
        existing_child = next((c for c in self.current_node.children if c.move == move), None)

        if existing_child is not None:
            self.current_node = existing_child
            self._sync_game_to_current_node()
        else:
            g = self.game
            g.play(move)
            new_node = GameNode(move, g.board, parent=self.current_node)
            self.current_node = new_node

        self.history.rebuild(self.root_node, self.current_node)
        self._after_move()

    def _on_click(self, x: int) -> None:
        g = self.game
        if g.is_over() or self._is_ai(g.player) or not g.board.is_legal(x):
            return
        self.play_move(x)

    def _ai_move(self) -> None:
        g = self.game
        if g.is_over() or not self._is_ai(g.player):
            return
        moves = g.legal_moves()
        if self.kind[g.player].currentText() == "Glouton":
            move = max(moves, key=lambda m: (len(g.board.flips(m)), random.random()))
        else:
            move = random.choice(moves)
        self.play_move(move)

    def _copy_transcript(self) -> None:
        QApplication.clipboard().setText(self.game.transcript())
        self._notice = "Transcript copié dans le presse-papiers."
        self._refresh()

    def _paste_transcript(self) -> None:
        """Remplace l'arbre par la partie dont le transcript est dans le presse-papiers."""
        text = QApplication.clipboard().text()
        if not text.strip():
            self._notice = "Le presse-papiers est vide."
            self._refresh()
            return
        if "(;" in text:                       # GGF collé
            self._load_ggf_text(text)
            return
        try:
            new_game = Game.from_transcript(text)
        except ValueError as e:
            QMessageBox.warning(self, "Transcript invalide", str(e))
            return

        root = GameNode(None, Board())
        curr = root
        for m in new_game.moves:
            curr = GameNode(m, curr.board, parent=curr)
            curr.board.make_move(m)
        self._install_tree(root, curr, "Transcript collé.")

    # ---- GGF --------------------------------------------------------------

    def _load_ggf_text(self, text: str) -> None:
        """Remplace l'arbre par la (première) partie du texte GGF."""
        try:
            games = parse_ggf(text)
        except ValueError as e:
            QMessageBox.warning(self, "GGF invalide", str(e))
            return
        game = games[0]
        root = GameNode(None, game.start)
        root.meta = {k: game.props[k] for k in ("PC", "DT", "RB", "RW", "TI", "TY")
                     if k in game.props}
        curr = root
        for m, sc, tm in zip(game.moves, game.scores, game.times):
            curr = GameNode(m, curr.board, parent=curr, score=sc, elapsed=tm)
            curr.board.make_move(m)
        players = {k: v for k, v in (("black", game.black), ("white", game.white)) if v}
        notice = "GGF chargé."
        if len(games) > 1:
            notice += f" (1re partie sur {len(games)})"
        self._install_tree(root, curr, notice, players or None)

    def _import_ggf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer une partie GGF", "", "Partie GGF (*.ggf *.txt);;Tous les fichiers (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.warning(self, "Lecture impossible", str(e))
            return
        self._load_ggf_text(text)

    def _export_ggf(self) -> None:
        """Exporte la ligne de jeu jusqu'au nœud courant (le GGF n'a pas de variantes)."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter en GGF", "partie.ggf", "Partie GGF (*.ggf)")
        if not path:
            return
        nodes = []
        n = self.current_node
        while n.parent is not None:
            nodes.append(n)
            n = n.parent
        nodes.reverse()
        text = to_ggf(self.root_node.board, [n.move for n in nodes],
                      black=self._name(BLACK), white=self._name(WHITE),
                      scores=[n.score for n in nodes], times=[n.elapsed for n in nodes],
                      meta=self.root_node.meta)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            QMessageBox.warning(self, "Enregistrement impossible", str(e))
            return
        self._notice = "Partie exportée en GGF."
        self._refresh()

    def _delete_current(self) -> None:
        """Supprime le coup sélectionné et tout son sous-arbre."""
        if self.current_node.parent is not None:
            self.history.delete_node(self.current_node)

    def _save_tree(self) -> None:
        """Enregistre l'arbre complet (variantes + position courante) en JSON."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer l'arbre", "partie.othello.json", "Arbre Othello (*.json)")
        if not path:
            return
        try:
            save_tree(path, self.root_node, self.current_node,
                      {"black": self._name(BLACK), "white": self._name(WHITE)})
        except OSError as e:
            QMessageBox.warning(self, "Enregistrement impossible", str(e))
            return
        self._notice = "Arbre enregistré."
        self._refresh()

    def _open_tree(self) -> None:
        """Remplace l'arbre courant par celui d'un fichier JSON."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un arbre", "", "Arbre Othello (*.json);;Tous les fichiers (*)")
        if not path:
            return
        try:
            root, current, players = load_tree(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Arbre invalide", str(e))
            return
        self._install_tree(root, current, "Arbre chargé.", players)

    def _install_tree(self, root: GameNode, current: GameNode, notice: str,
                      players: dict[str, str] | None = None) -> None:
        """Remplace l'arbre par (root, current), après confirmation s'il y a des coups.
        `players` : noms à appliquer ; None laisse les noms actuels inchangés."""
        if self.root_node.children:
            answer = QMessageBox.question(
                self, "Remplacer l'arbre", "L'arbre actuel sera remplacé. Continuer ?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.root_node = root
        self.current_node = current
        self._sync_game_to_current_node()
        if players is not None:
            for color, key in ((BLACK, "black"), (WHITE, "white")):
                self.name_edit[color].setText(players.get(key, self.NAMES[color]))
        self.history.rebuild(self.root_node, self.current_node)
        self._after_move(notice)

    def _on_hints(self, checked: bool) -> None:
        self.board_view.show_hints = checked
        self.board_view.update()

    # ---- courbes ----------------------------------------------------------

    def _line_nodes(self) -> tuple[list[GameNode], int]:
        """Ligne de jeu affichée : racine -> nœud courant, prolongée par les premiers
        enfants. Retourne (nœuds du ply 1 à la fin, ply courant)."""
        line: list[GameNode] = []
        n = self.current_node
        while n.parent is not None:
            line.append(n)
            n = n.parent
        line.reverse()
        cur = len(line)
        n = self.current_node
        while n.children:
            n = n.children[0]
            line.append(n)
        return line, cur

    def _goto_ply(self, ply: int) -> None:
        line, _ = self._line_nodes()
        if 1 <= ply <= len(line) and line[ply - 1] is not self.current_node:
            self.history._goto(line[ply - 1])

    def _refresh_charts(self) -> None:
        line, cur = self._line_nodes()
        score = {BLACK: [], WHITE: []}
        elapsed = {BLACK: [], WHITE: []}
        total, acc = {BLACK: [], WHITE: []}, [0.0, 0.0]
        for ply, node in enumerate(line, 1):
            if node.move == PASS:
                continue
            c = node.parent.board.player
            if node.score is not None:
                score[c].append((ply, node.score))
            acc[c] += node.elapsed or 0.0
            if node.elapsed is not None:
                elapsed[c].append((ply, node.elapsed))
                total[c].append((ply, acc[c]))

        def series(data: dict) -> list[Series]:
            return [
                Series(self._name(BLACK), QColor("#546e7a"), QColor("#111111"),
                       QColor("#cfd8dc"), data[BLACK]),
                Series(self._name(WHITE), QColor("#b0bec5"), QColor("#ffffff"),
                       QColor("#37474f"), data[WHITE]),
            ]

        if self.black_pov_check.isChecked():
            # une seule courbe : éval de Blanc inversée ; points noirs / blancs selon le joueur
            kb = (QColor("#111111"), QColor("#cfd8dc"))
            kw = (QColor("#ffffff"), QColor("#37474f"))
            merged = sorted([(p, v, kb) for p, v in score[BLACK]]
                            + [(p, -v, kw) for p, v in score[WHITE]], key=lambda t: t[0])
            score_series = [Series(
                "Avantage", QColor("#78909c"), kb[0], kb[1],
                [(p, v) for p, v, _ in merged], [k for _, _, k in merged],
                [(*kb, self._name(BLACK)), (*kw, self._name(WHITE))])]
        else:
            score_series = series(score)
        self.score_chart.set_data(score_series, cur, len(line))
        self.time_chart.set_data(series(total if self.cum_check.isChecked() else elapsed),
                                 cur, len(line))

    def _clocks(self):
        """([restant noir, restant blanc], prolongation) à la position courante, ou None."""
        tc = parse_time_control(self.root_node.meta.get("TI"))
        if tc is None:
            return None
        init, inc, extra = tc
        used, count = [0.0, 0.0], [0, 0]
        node = self.current_node
        while node.parent is not None:
            if node.move != PASS:
                c = node.parent.board.player
                count[c] += 1
                used[c] += node.elapsed or 0.0
            node = node.parent
        return [init + inc * count[c] - used[c] for c in (BLACK, WHITE)], extra

    def _clock_text(self, main: float, extra: float) -> tuple[str, str]:
        """(texte, css) : temps principal, puis prolongation (orange), puis dépassé (rouge)."""
        if main >= 0:
            return fmt_clock(main), ""
        if extra + main >= 0:
            return "+" + fmt_clock(extra + main), "color: #e65100;"
        return "0:00", "color: #c62828;"

    def _refresh(self) -> None:
        g = self.game
        b = g.board
        over = g.is_over()
        ai_turn = not over and self._is_ai(g.player)

        gray = self.palette().color(QPalette.ColorGroup.Disabled,
                                    QPalette.ColorRole.WindowText).name()
        winner = g.winner() if over else None
        for color in (BLACK, WHITE):
            current = (not over) and g.player == color
            dimmed = (not over) and not current          # le joueur qui n'a pas le trait
            bold = current or (over and winner == color)
            weight = 700 if bold else 400
            tone = f"color: {gray};" if dimmed else ""
            # cadre du cartouche : surligné pour le joueur au trait, vert pour le vainqueur
            pal = self.palette()
            if current:
                hl = pal.color(QPalette.ColorRole.Highlight)
                frame_css = (f"border: 2px solid {hl.name()}; "
                             f"background: rgba({hl.red()}, {hl.green()}, {hl.blue()}, 38);")
            elif over and winner == color:
                frame_css = "border: 2px solid #2e7d32; background: rgba(46, 125, 50, 38);"
            else:
                frame_css = (f"border: 2px solid {pal.color(QPalette.ColorRole.Mid).name()}; "
                             f"background: transparent;")
            self._set_style(self.player_frame[color],
                            f"QFrame#playerFrame {{ {frame_css} border-radius: 7px; }}")
            self.disc_label[color].setText(str(b.n_discs[color]))
            self._set_style(self.disc_label[color], f"font-size: 17px; font-weight: {weight}; {tone}")
            self._set_style(self.glyph_label[color], f"font-size: 17px; font-weight: {weight}; {tone}")
            self._set_style(
                self.name_edit[color],
                f"QLineEdit {{ border: none; background: transparent; font-size: 15px; "
                f"font-weight: {weight}; {tone} }} "
                f"QLineEdit:focus {{ border-bottom: 1px solid palette(highlight); }}")

        clocks = self._clocks()
        for color in (BLACK, WHITE):
            if clocks is None:
                self.clock_label[color].setText("")
                continue
            text_c, css = self._clock_text(clocks[0][color], clocks[1])
            bold = (not over) and g.player == color
            self.clock_label[color].setText(text_c)
            self._set_style(self.clock_label[color],
                            f"font-family: monospace; font-size: 17px; "
                            f"font-weight: {700 if bold else 400}; {css}")

        meta = self.root_node.meta
        info = []
        if meta.get("TY"):
            info.append("Type : " + describe_type(meta["TY"]))
        tc = parse_time_control(meta.get("TI"))
        if tc:
            t = f"Cadence : {fmt_clock(tc[0])} par joueur"
            if tc[1]:
                t += f" + {tc[1]:g}s/coup"
            if tc[2]:
                t += f", prolongation {fmt_clock(tc[2])}"
            info.append(t)
        self.info.setText("\n".join(info))
        self.info.setVisible(bool(info))

        if over:
            sb, sw = g.result()
            text = ("Égalité" if winner not in (BLACK, WHITE) else f"{self._name(winner)} gagne") + f" {sb}–{sw}"
        else:
            text = "Réfléchit…" if ai_turn else ""
        if self._notice:
            text += ("\n" if text else "") + self._notice
        self.status.setText(text)

        self._refresh_charts()
        self.act_delete.setEnabled(self.current_node.parent is not None)
        self.board_view.interactive = not over and not ai_turn
        self.board_view.last_move = next((m for m in reversed(g.moves) if m != PASS), None)
        self.board_view.update()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
