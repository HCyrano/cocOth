"""othello_board.py : plateau et gestion de partie d'Othello/Reversi.

Port Python des conventions de solver.c (R. Delorme) :
  - plateau 1-D de 91 cases avec sentinelles OFF_SIDE (A1 = 10, ..., H8 = 80),
  - couleurs BLACK=0, WHITE=1, EMPTY=2, OFF_SIDE=3,
  - NOMOVE=0, PASS=1,
  - format texte 64 cases (b/x/* noir, o/w blanc, -/. vide) + joueur au trait,
  - score final = différence de pions, cases vides attribuées au gagnant.

Deux niveaux :
  - Board : position + make_move / undo_move (pile d'historique), pas de règles
            de fin de partie au-delà de is_game_over().
  - Game  : partie complète (coups, passes, undo/redo, transcript, résultat).
"""

from __future__ import annotations

from enum import IntEnum
from typing import Iterable

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

BLACK, WHITE, EMPTY, OFF_SIDE = 0, 1, 2, 3
NOMOVE, PASS = 0, 1
BOARD_SIZE = 91

# NW, N, NE, W, E, SW, S, SE (stride 9 : une colonne sentinelle par ligne)
DIRECTIONS = (-10, -9, -8, -1, 1, 8, 9, 10)

COLUMNS = "abcdefgh"

# A1..H8 en ordre ligne par ligne (A1, B1, ..., H1, A2, ...), comme solver.c
SQUARES = tuple(r * 9 + c for r in range(1, 9) for c in range(1, 9))

Sq = IntEnum("Sq", {f"{COLUMNS[c - 1].upper()}{r}": r * 9 + c
                    for r in range(1, 9) for c in range(1, 9)})

_DISC_CHAR = "*O-"          # BLACK, WHITE, EMPTY
_PLAYER_NAME = ("Black", "White")


class IllegalMoveError(ValueError):
    """Coup illégal pour la position courante."""


def opponent(player: int) -> int:
    return player ^ 1


def sq_to_str(x: int) -> str:
    """10 -> 'a1', 80 -> 'h8' ; PASS -> 'pass'."""
    if x == PASS:
        return "pass"
    if not (0 <= x < BOARD_SIZE) or x % 9 == 0 or not (1 <= x // 9 <= 8):
        raise ValueError(f"case invalide : {x}")
    return f"{COLUMNS[x % 9 - 1]}{x // 9}"


def str_to_sq(s: str) -> int:
    """'d3' / 'D3' -> 31 ; 'pass' / '--' -> PASS."""
    s = s.strip().lower()
    if s in ("pass", "pa", "--"):
        return PASS
    if len(s) != 2 or s[0] not in COLUMNS or s[1] not in "12345678":
        raise ValueError(f"coup invalide : {s!r}")
    return int(s[1]) * 9 + COLUMNS.index(s[0]) + 1


def _to_move(move: int | str) -> int:
    return str_to_sq(move) if isinstance(move, str) else int(move)


# --------------------------------------------------------------------------
# Board
# --------------------------------------------------------------------------

class Board:
    """Position d'Othello avec make_move / undo_move.

    Attributs : square (liste de 91), player (au trait), n_discs[2], n_empties.
    """

    __slots__ = ("square", "player", "n_discs", "n_empties", "_history")

    def __init__(self, string: str | None = None) -> None:
        self._history: list[tuple[int, tuple[int, ...]]] = []
        if string is None:
            self._set_initial()
        else:
            self._set_from_string(string)

    # ---- construction ----------------------------------------------------

    @classmethod
    def initial(cls) -> "Board":
        return cls()

    @classmethod
    def from_string(cls, string: str) -> "Board":
        return cls(string)

    def _set_initial(self) -> None:
        self.square = [OFF_SIDE] * BOARD_SIZE
        for x in SQUARES:
            self.square[x] = EMPTY
        self.square[Sq.D4] = self.square[Sq.E5] = WHITE
        self.square[Sq.E4] = self.square[Sq.D5] = BLACK
        self.player = BLACK
        self.n_discs = [2, 2]
        self.n_empties = 60

    def _set_from_string(self, string: str) -> None:
        """Même format que board_set() de solver.c : 64 cases puis le joueur.

        Les caractères non reconnus (espaces, retours ligne...) sont ignorés.
        """
        self.square = [OFF_SIDE] * BOARD_SIZE
        self.n_discs = [0, 0]
        self.n_empties = 0
        it = iter(string)
        for x in SQUARES:
            for ch in it:
                ch = ch.lower()
                if ch in "bx*":
                    self.square[x] = BLACK
                    self.n_discs[BLACK] += 1
                elif ch in "ow":
                    self.square[x] = WHITE
                    self.n_discs[WHITE] += 1
                elif ch in "-.":
                    self.square[x] = EMPTY
                    self.n_empties += 1
                else:
                    continue
                break
            else:
                raise ValueError("description de plateau incomplète (64 cases attendues)")
        player = None
        for ch in it:
            ch = ch.lower()
            if ch in "bx*":
                player = BLACK
                break
            if ch in "ow":
                player = WHITE
                break
        if player is None:
            raise ValueError("joueur au trait manquant")
        self.player = player

    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b.square = self.square[:]
        b.player = self.player
        b.n_discs = self.n_discs[:]
        b.n_empties = self.n_empties
        b._history = self._history[:]
        return b

    # ---- sérialisation ---------------------------------------------------

    def to_string(self) -> str:
        """64 cases + joueur au trait, ex. '---...--- *' (relisible par from_string)."""
        cells = "".join(_DISC_CHAR[self.square[x]] for x in SQUARES)
        return f"{cells} {_DISC_CHAR[self.player]}"

    def __str__(self) -> str:
        """Rendu ASCII façon board_print() ; '.' marque les coups légaux."""
        legal = set(self.legal_moves())
        lines = ["  A B C D E F G H"]
        for r in range(1, 9):
            row = " ".join(
                "." if (r * 9 + c) in legal else _DISC_CHAR[self.square[r * 9 + c]]
                for c in range(1, 9)
            )
            line = f"{r} {row} {r}"
            if r == 2:
                line += f" {_DISC_CHAR[self.player]} to move"
            elif r == 4:
                line += f" *: discs = {self.n_discs[BLACK]:2d}    moves = {self.mobility(BLACK):2d}"
            elif r == 5:
                line += f" O: discs = {self.n_discs[WHITE]:2d}    moves = {self.mobility(WHITE):2d}"
            elif r == 6:
                line += f"  empties = {self.n_empties:2d}      ply = {61 - self.n_empties:2d}"
            lines.append(line)
        lines.append("  A B C D E F G H")
        return "\n".join(lines)

    __repr__ = __str__

    # ---- règles : légalité et flips -------------------------------------

    def _captures(self, x: int, p: int) -> bool:
        """True si jouer x est légal pour p (sortie anticipée)."""
        sq = self.square
        o = p ^ 1
        for d in DIRECTIONS:
            y = x + d
            if sq[y] == o:
                y += d
                while sq[y] == o:
                    y += d
                if sq[y] == p:
                    return True
        return False

    def flips(self, x: int, player: int | None = None) -> list[int]:
        """Cases retournées si `player` (défaut : au trait) joue x ; [] si illégal."""
        if not (0 <= x < BOARD_SIZE) or self.square[x] != EMPTY:
            return []
        p = self.player if player is None else player
        o = p ^ 1
        sq = self.square
        out: list[int] = []
        for d in DIRECTIONS:
            y = x + d
            run = []
            while sq[y] == o:
                run.append(y)
                y += d
            if run and sq[y] == p:
                out += run
        return out

    def is_legal(self, x: int, player: int | None = None) -> bool:
        if not (0 <= x < BOARD_SIZE) or self.square[x] != EMPTY:
            return False
        return self._captures(x, self.player if player is None else player)

    def legal_moves(self, player: int | None = None) -> list[int]:
        """Coups légaux (cases, sans PASS), ordre A1, B1, ..., H8."""
        p = self.player if player is None else player
        sq = self.square
        return [x for x in SQUARES if sq[x] == EMPTY and self._captures(x, p)]

    def mobility(self, player: int | None = None) -> int:
        return len(self.legal_moves(player))

    def has_move(self, player: int | None = None) -> bool:
        p = self.player if player is None else player
        sq = self.square
        return any(sq[x] == EMPTY and self._captures(x, p) for x in SQUARES)

    def must_pass(self) -> bool:
        """Le joueur au trait n'a aucun coup mais l'adversaire en a un."""
        return not self.has_move() and self.has_move(self.player ^ 1)

    def is_game_over(self) -> bool:
        return not self.has_move() and not self.has_move(self.player ^ 1)

    # ---- make / undo ------------------------------------------------------

    def make_move(self, move: int | str) -> tuple[int, ...]:
        """Joue `move` (case, 'd3' ou PASS) pour le joueur au trait.

        Retourne les cases retournées. Lève IllegalMoveError si illégal.
        PASS n'est accepté que si le joueur n'a aucun coup légal.
        """
        x = _to_move(move)
        if x == PASS:
            if self.has_move():
                raise IllegalMoveError("passe interdite : des coups sont possibles")
            self._history.append((PASS, ()))
            self.player ^= 1
            return ()
        fl = self.flips(x)
        if not fl:
            name = sq_to_str(x) if 0 < x < BOARD_SIZE and x % 9 else x
            raise IllegalMoveError(f"coup illégal : {name}")
        p = self.player
        o = p ^ 1
        sq = self.square
        sq[x] = p
        for f in fl:
            sq[f] = p
        n = len(fl)
        self.n_discs[p] += n + 1
        self.n_discs[o] -= n
        self.n_empties -= 1
        self.player = o
        flips = tuple(fl)
        self._history.append((x, flips))
        return flips

    def undo_move(self) -> int:
        """Annule le dernier coup (ou passe) ; retourne ce coup. IndexError si vide."""
        if not self._history:
            raise IndexError("rien à annuler")
        x, fl = self._history.pop()
        self.player ^= 1
        if x == PASS:
            return PASS
        p = self.player
        o = p ^ 1
        sq = self.square
        sq[x] = EMPTY
        for f in fl:
            sq[f] = o
        n = len(fl)
        self.n_discs[p] -= n + 1
        self.n_discs[o] += n
        self.n_empties += 1
        return x

    @property
    def history(self) -> list[int]:
        """Coups joués sur ce plateau depuis sa création (PASS inclus)."""
        return [m for m, _ in self._history]

    # ---- score ------------------------------------------------------------

    def final_score(self) -> int:
        """Score du joueur au trait, cases vides au gagnant (cf. board_get_final_score).

        Significatif en fin de partie ; sinon simple convention appliquée à la position.
        """
        p = self.player
        score = self.n_discs[p] - self.n_discs[p ^ 1]
        if score > 0:
            score += self.n_empties
        elif score < 0:
            score -= self.n_empties
        return score


# --------------------------------------------------------------------------
# Game
# --------------------------------------------------------------------------

class Game:
    """Partie complète : coups, passes, undo/redo, transcript, résultat."""

    def __init__(self, board: Board | None = None) -> None:
        self.board = board.copy() if board is not None else Board()
        self.start = self.board.to_string()
        self.moves: list[int] = []      # coups joués, PASS inclus
        self._redo: list[int] = []

    # ---- état -------------------------------------------------------------

    @property
    def player(self) -> int:
        return self.board.player

    @property
    def ply(self) -> int:
        return len(self.moves)

    def legal_moves(self) -> list[int]:
        """Coups légaux ; [PASS] si passe forcée ; [] si la partie est finie."""
        moves = self.board.legal_moves()
        if moves:
            return moves
        return [PASS] if self.board.must_pass() else []

    def is_over(self) -> bool:
        return self.board.is_game_over()

    def reset(self) -> None:
        self.board = Board(self.start)
        self.moves.clear()
        self._redo.clear()

    # ---- jouer / annuler --------------------------------------------------

    def play(self, move: int | str) -> tuple[int, ...]:
        """Joue un coup (case, 'd3', PASS/'pass'). Efface la pile de redo."""
        x = _to_move(move)
        flips = self.board.make_move(x)
        self.moves.append(x)
        self._redo.clear()
        return flips

    def undo(self) -> int | None:
        """Annule le dernier coup ; None s'il n'y en a pas."""
        if not self.moves:
            return None
        self.board.undo_move()
        x = self.moves.pop()
        self._redo.append(x)
        return x

    def redo(self) -> int | None:
        if not self._redo:
            return None
        x = self._redo.pop()
        self.board.make_move(x)
        self.moves.append(x)
        return x

    # ---- résultat ---------------------------------------------------------

    def result(self) -> tuple[int, int] | None:
        """(score_noir, score_blanc), cases vides au gagnant ; None si non terminée."""
        if not self.is_over():
            return None
        b, w = self.board.n_discs
        if b > w:
            b += self.board.n_empties
        elif w > b:
            w += self.board.n_empties
        return b, w

    def winner(self) -> int:
        """BLACK, WHITE ou EMPTY (nulle). Lève RuntimeError si non terminée."""
        r = self.result()
        if r is None:
            raise RuntimeError("partie non terminée")
        return BLACK if r[0] > r[1] else WHITE if r[1] > r[0] else EMPTY

    # ---- transcript -------------------------------------------------------

    def transcript(self, with_passes: bool = False) -> str:
        """'f5d6c3...' ; les passes sont implicites sauf with_passes=True."""
        return "".join(sq_to_str(m) for m in self.moves
                       if with_passes or m != PASS)

    def play_transcript(self, transcript: str | Iterable[str]) -> None:
        """Rejoue une suite de coups ('f5d6...' ou liste) ; insère les passes forcées."""
        if isinstance(transcript, str):
            s = "".join(transcript.split()).lower()
            if len(s) % 2:
                raise ValueError("transcript de longueur impaire")
            items: Iterable[str] = (s[i:i + 2] for i in range(0, len(s), 2))
        else:
            items = transcript
        for item in items:
            x = _to_move(item)
            if x != PASS and not self.board.is_legal(x) and self.board.must_pass():
                self.play(PASS)
            self.play(x)

    @classmethod
    def from_transcript(cls, transcript: str, board: Board | None = None) -> "Game":
        g = cls(board)
        g.play_transcript(transcript)
        return g

    def __str__(self) -> str:
        return str(self.board)


# --------------------------------------------------------------------------
# Utilitaire de validation
# --------------------------------------------------------------------------

def perft(board: Board, depth: int) -> int:
    """Nombre de feuilles à `depth` coups ; une passe forcée compte comme un coup,
    une position terminale est une feuille. Exerce make_move/undo_move."""
    if depth == 0:
        return 1
    moves = board.legal_moves()
    if not moves:
        if not board.has_move(board.player ^ 1):
            return 1
        moves = [PASS]
    total = 0
    for m in moves:
        board.make_move(m)
        total += perft(board, depth - 1)
        board.undo_move()
    return total


if __name__ == "__main__":
    g = Game()
    print(g)
    for m in ("f5", "d6", "c3"):
        g.play(m)
    print()
    print(g)
    print("transcript :", g.transcript())
