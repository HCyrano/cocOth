#!/usr/bin/env python3
"""history_tree.py : arbre d'historique (variantes) pour l'interface Othello.

- GameNode : nœud logique de l'arbre des coups.
- HistoryTreeWidget : QTreeWidget qui route les flèches haut/bas vers le contrôleur.
- tree_to_dict / tree_from_dict / save_tree / load_tree : sauvegarde de l'arbre complet
  (toutes les variantes + position courante) au format JSON.
- HistoryTreeController : construit l'arbre visuel, gère la navigation, la sélection
  et la suppression d'un coup (clic droit) avec tout son sous-arbre.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from othello_board import PASS, Board, IllegalMoveError, sq_to_str, str_to_sq


# --------------------------------------------------------------------------
# Nœud de l'arbre d'historique
# --------------------------------------------------------------------------

class GameNode:
    """Représente un nœud dans l'arbre des coups (variantes)."""

    def __init__(self, move: int | None, board: Board, parent: GameNode | None = None,
                 score: float | None = None, elapsed: float | None = None) -> None:
        self.move = move  # Coup joué pour arriver ici (None pour la racine)
        self.score = score      # éval du joueur qui a joué ce coup (None si inconnue)
        self.elapsed = elapsed  # temps de réflexion en secondes (None si inconnu)
        self.meta: dict[str, str] = {}  # infos de partie (TY, TI, RB...) : utilisé sur la racine
        self.board = board.copy()  # État du plateau à ce nœud
        self.parent = parent
        self.children: list[GameNode] = []
        if parent is not None:
            parent.children.append(self)


# --------------------------------------------------------------------------
# Sauvegarde / chargement JSON de l'arbre complet
# --------------------------------------------------------------------------
#
# Format :
#   {"format": "othello-tree", "version": 1,
#    "tree": {"move": null, "children": [{"move": "f5", "children": [...]}, ...]},
#    "current": [0, 1],        # chemin (indices d'enfants) de la racine au nœud courant
#    "players": {"black": "Noir", "white": "Blanc"},   # optionnel : noms des joueurs
#    "start": "---...--- *"}                           # optionnel : départ non standard
# Les coups sont écrits en notation "f5" ; une passe s'écrit "pass".

FORMAT_NAME = "othello-tree"
FORMAT_VERSION = 1


PLAYER_KEYS = ("black", "white")


def tree_to_dict(root: GameNode, current: GameNode,
                 players: dict[str, str] | None = None) -> dict[str, Any]:
    """Sérialise l'arbre sous `root`, la position `current` et, si fournis, les noms
    des joueurs ({"black": ..., "white": ...}). Itératif."""
    out: dict[str, Any] = {"move": None, "children": []}
    stack: list[tuple[GameNode, dict[str, Any]]] = [(root, out)]
    while stack:
        node, d = stack.pop()
        for child in node.children:
            cd: dict[str, Any] = {"move": sq_to_str(child.move), "children": []}
            if child.score is not None:
                cd["score"] = child.score
            if child.elapsed is not None:
                cd["time"] = child.elapsed
            d["children"].append(cd)
            stack.append((child, cd))

    path: list[int] = []
    n = current
    while n.parent is not None:
        path.append(n.parent.children.index(n))
        n = n.parent
    path.reverse()
    data: dict[str, Any] = {"format": FORMAT_NAME, "version": FORMAT_VERSION,
                            "tree": out, "current": path}
    if players is not None:
        data["players"] = {k: players[k] for k in PLAYER_KEYS if k in players}
    if root.meta:
        data["meta"] = dict(root.meta)
    if root.board.to_string() != Board().to_string():   # départ non standard (ex. GGF)
        data["start"] = root.board.to_string()
    return data


def tree_from_dict(data: Any) -> tuple[GameNode, GameNode, dict[str, str] | None]:
    """Reconstruit (racine, nœud courant, noms des joueurs ou None si absents).
    Lève ValueError si le contenu est invalide.

    Chaque coup est rejoué depuis la position initiale : un coup illégal, un doublon
    parmi les frères ou un coup après la fin de partie est refusé.
    """
    if not isinstance(data, dict) or data.get("format") != FORMAT_NAME:
        raise ValueError("ce fichier n'est pas un arbre Othello")
    if data.get("version") != FORMAT_VERSION:
        raise ValueError(f"version non supportée : {data.get('version')!r}")
    tree = data.get("tree")
    if not isinstance(tree, dict) or tree.get("move") is not None:
        raise ValueError("racine invalide")

    start = data.get("start")
    try:
        root = GameNode(None, Board(start) if start is not None else Board())
    except (ValueError, TypeError):
        raise ValueError("position de départ invalide") from None
    meta = data.get("meta")
    if meta is not None:
        if not isinstance(meta, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in meta.items()):
            raise ValueError("infos de partie invalides")
        root.meta = dict(meta)
    stack: list[tuple[GameNode, dict]] = [(root, tree)]
    while stack:
        node, d = stack.pop()
        children = d.get("children", [])
        if not isinstance(children, list):
            raise ValueError("liste d'enfants invalide")
        seen: set[int] = set()
        for cd in children:
            if not isinstance(cd, dict) or not isinstance(cd.get("move"), str):
                raise ValueError("nœud invalide")
            where = _describe(node)
            try:
                move = str_to_sq(cd["move"])
            except ValueError as e:
                raise ValueError(f"{e} (après {where})") from None
            if move in seen:
                raise ValueError(f"coup en double {cd['move']!r} (après {where})")
            seen.add(move)
            if node.board.is_game_over():
                raise ValueError(f"coup {cd['move']!r} après la fin de partie (après {where})")
            child = GameNode(move, node.board, parent=node,
                             score=_opt_num(cd.get("score")), elapsed=_opt_num(cd.get("time")))
            try:
                child.board.make_move(move)
            except IllegalMoveError as e:
                node.children.remove(child)
                raise ValueError(f"{e} (après {where})") from None
            stack.append((child, cd))

    current = root
    path = data.get("current", [])
    if not isinstance(path, list):
        raise ValueError("position courante invalide")
    for i in path:
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(current.children):
            raise ValueError("position courante invalide")
        current = current.children[i]

    players = data.get("players")
    if players is not None:
        if (not isinstance(players, dict)
                or any(k not in PLAYER_KEYS or not isinstance(v, str) for k, v in players.items())):
            raise ValueError("noms de joueurs invalides")
    return root, current, players


def _opt_num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("score ou temps invalide")
    return float(v)


def _describe(node: GameNode) -> str:
    """Chemin lisible de la racine à `node` (pour les messages d'erreur)."""
    moves = []
    while node.parent is not None:
        moves.append(sq_to_str(node.move))
        node = node.parent
    return " ".join(reversed(moves)) or "la position initiale"


def save_tree(path: str, root: GameNode, current: GameNode,
              players: dict[str, str] | None = None) -> None:
    """Écrit l'arbre en JSON (écriture atomique : fichier temporaire puis remplacement)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tree_to_dict(root, current, players), f, separators=(",", ":"),
                  ensure_ascii=False)
    os.replace(tmp, path)


def load_tree(path: str) -> tuple[GameNode, GameNode, dict[str, str] | None]:
    """Lit un fichier JSON ; lève ValueError (contenu) ou OSError (fichier)."""
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as e:
            raise ValueError(f"JSON illisible : {e}") from None
    return tree_from_dict(data)


# --------------------------------------------------------------------------
# Widget : les flèches haut/bas sont déléguées au contrôleur
# --------------------------------------------------------------------------

class HistoryTreeWidget(QTreeWidget):
    """Navigation dans la branche courante avec les flèches haut et bas."""

    def __init__(self, controller: HistoryTreeController) -> None:
        super().__init__()
        self._controller = controller

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Up:
            self._controller.navigate_up()
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            self._controller.navigate_down()
            event.accept()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------
# Contrôleur
# --------------------------------------------------------------------------

class HistoryTreeController:
    """Pilote l'arbre d'historique.

    La fenêtre garde la propriété de `current_node` ; le contrôleur la lit et la
    modifie via les callbacks fournis :
      - get_current_node() -> GameNode
      - set_current_node(node)
      - sync_game() : aligne l'objet Game sur le nœud courant
      - kick() : relance l'IA / rafraîchit l'affichage
    """

    def __init__(
        self,
        get_current_node: Callable[[], GameNode],
        set_current_node: Callable[[GameNode], None],
        sync_game: Callable[[], None],
        kick: Callable[[], None],
    ) -> None:
        self._get_current = get_current_node
        self._set_current = set_current_node
        self._sync_game = sync_game
        self._kick = kick
        self._root: GameNode | None = None
        self._updating = False

        self.widget = HistoryTreeWidget(self)
        self.widget.currentItemChanged.connect(self._on_select)
        self.widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.widget.customContextMenuRequested.connect(self._on_context_menu)

    # ---- navigation -------------------------------------------------------

    def navigate_up(self) -> None:
        """Revient au parent du coup sélectionné."""
        node = self._get_current()
        if node.parent is None:
            return
        self._goto(node.parent)

    def navigate_down(self) -> None:
        """Avance dans une continuation visible, sans entrer dans une variante repliée."""
        node = self._get_current()
        children = node.children
        if not children:
            return

        if len(children) == 1:
            # Pas de bifurcation : la continuation est toujours navigable.
            next_node = children[0]
        else:
            # À une bifurcation, seules les variantes dépliées sont actives.
            # Une variante repliée ne doit pas bloquer une autre variante ouverte.
            visible = []
            for child in children:
                item = self._find_item(child)
                if item is not None and item.isExpanded():
                    visible.append(child)
            if not visible:
                return
            next_node = visible[0]
        self._goto(next_node)

    def _goto(self, node: GameNode) -> None:
        self._set_current(node)
        self._sync_game()
        self.rebuild(self._root_of(node), node)
        self._kick()

    @staticmethod
    def _root_of(node: GameNode) -> GameNode:
        while node.parent is not None:
            node = node.parent
        return node

    # ---- sélection --------------------------------------------------------

    def _on_select(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if self._updating or current is None:
            return
        node = current.data(0, Qt.ItemDataRole.UserRole)
        if node is not None:
            self._set_current(node)
            self._sync_game()
            self._kick()

    # ---- suppression (clic droit) ----------------------------------------

    def _on_context_menu(self, pos) -> None:
        item = self.widget.itemAt(pos)
        if item is None:
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node is None or node.parent is None:  # la position initiale n'est pas supprimable
            return

        n_desc = self._count(node) - 1
        label = "Supprimer ce coup" + (f" et ses {n_desc} descendant(s)" if n_desc else "")
        menu = QMenu(self.widget)
        action = menu.addAction(label)
        if menu.exec(self.widget.viewport().mapToGlobal(pos)) is action:
            self.delete_node(node)

    @classmethod
    def _count(cls, node: GameNode) -> int:
        return 1 + sum(cls._count(c) for c in node.children)

    def delete_node(self, node: GameNode) -> None:
        """Supprime `node` et tout son sous-arbre."""
        if node.parent is None:
            return
        # Si la position courante est dans le sous-arbre supprimé, on remonte au parent.
        n: GameNode | None = self._get_current()
        while n is not None:
            if n is node:
                self._set_current(node.parent)
                break
            n = n.parent
        node.parent.children.remove(node)
        self._sync_game()
        current = self._get_current()
        self.rebuild(self._root_of(current), current)
        self._kick()

    # ---- construction de l'arbre visuel ----------------------------------

    def _find_item(self, target: GameNode) -> QTreeWidgetItem | None:
        def search(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, Qt.ItemDataRole.UserRole) is target:
                return item
            for i in range(item.childCount()):
                found = search(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self.widget.topLevelItemCount()):
            found = search(self.widget.topLevelItem(i))
            if found is not None:
                return found
        return None

    @staticmethod
    def _ply(node: GameNode) -> int:
        p = 0
        while node.parent is not None:
            p += 1
            node = node.parent
        return p

    def rebuild(self, root: GameNode, current: GameNode) -> None:
        """Reconstruit l'arbre en gardant les suites linéaires attachées au même parent
        pour éviter l'effet d'escalier, et n'indente qu'en cas de véritables variantes."""
        self._root = root
        self._updating = True
        try:
            # Mémorise les branches repliées avant de reconstruire l'arbre.
            collapsed: set[GameNode] = set()

            def remember(item: QTreeWidgetItem) -> None:
                node = item.data(0, Qt.ItemDataRole.UserRole)
                if node is not None and item.childCount() > 0 and not item.isExpanded():
                    collapsed.add(node)
                for i in range(item.childCount()):
                    remember(item.child(i))

            for i in range(self.widget.topLevelItemCount()):
                remember(self.widget.topLevelItem(i))
            self.widget.clear()

            root_item = QTreeWidgetItem(self.widget, ["0. Position initiale"])
            root_item.setData(0, Qt.ItemDataRole.UserRole, root)

            def label(node: GameNode, variant: bool = False) -> str:
                ply = self._ply(node)
                color = "●" if (ply - 1) % 2 == 0 else "○"
                move = "--" if node.move == PASS else sq_to_str(node.move)
                text = f"{ply:2d}. {color} {move}"
                if node.score is not None or node.elapsed is not None:
                    text += "  " + (f"{node.score:+6.2f}" if node.score is not None else " " * 6)
                    if node.elapsed is not None:
                        text += f" {node.elapsed:6.2f}s"
                return text + (" [Variante]" if variant else "")

            def add_branch(node: GameNode, parent_item: QTreeWidgetItem) -> None:
                curr = node
                # Tant qu'il n'y a qu'un seul enfant, on les ajoute tous au même parent_item
                # pour qu'ils s'alignent verticalement sans décalage en cascade.
                while len(curr.children) == 1:
                    curr = curr.children[0]
                    item = QTreeWidgetItem(parent_item, [label(curr)])
                    item.setData(0, Qt.ItemDataRole.UserRole, curr)

                # Bifurcation : sous-branches indentées, une par variante.
                if len(curr.children) > 1:
                    for child in curr.children:
                        branch = QTreeWidgetItem(parent_item, [label(child, variant=True)])
                        branch.setData(0, Qt.ItemDataRole.UserRole, child)
                        add_branch(child, branch)

            add_branch(root, root_item)
            self.widget.expandAll()

            def restore(item: QTreeWidgetItem) -> None:
                if item.data(0, Qt.ItemDataRole.UserRole) in collapsed:
                    item.setExpanded(False)
                for j in range(item.childCount()):
                    restore(item.child(j))

            for i in range(self.widget.topLevelItemCount()):
                restore(self.widget.topLevelItem(i))

            it = self._find_item(current)
            if it is not None:
                self.widget.setCurrentItem(it)
        finally:
            self._updating = False
