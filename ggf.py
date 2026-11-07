#!/usr/bin/env python3
"""ggf.py : lecture / écriture du format GGF (Generic Game Format, GGS) pour Othello.

Module pur (aucune dépendance Qt), ne dépend que de othello_board.

Lecture  : parse_ggf(texte) -> [GGFGame, ...]   (ValueError si invalide)
           Position de départ (BO), coups (B[..]/W[..]) rejoués et validés ;
           les passes implicites sont insérées, les passes explicites (PA) vérifiées.
           Les suffixes /éval/temps des coups sont ignorés.
Écriture : to_ggf(start, moves, black=..., white=...) -> str
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from othello_board import BLACK, PASS, WHITE, Board, sq_to_str, str_to_sq

_GAME = re.compile(r"\(\s*;(.*?);\s*\)", re.S)
_PROP = re.compile(r"([A-Za-z]+)\s*\[((?:\\.|[^\]\\])*)\]", re.S)


@dataclass
class GGFGame:
    start: Board                                  # position de départ (BO)
    moves: list[int]                              # coups, PASS inclus
    props: dict[str, str] = field(default_factory=dict)   # GM, PB, PW, DT, RE, TI, TY...
    scores: list[float | None] = field(default_factory=list)  # éval du joueur qui joue, par coup
    times: list[float | None] = field(default_factory=list)   # temps de réflexion (s), par coup

    @property
    def black(self) -> str | None:
        return self.props.get("PB")

    @property
    def white(self) -> str | None:
        return self.props.get("PW")


def _num(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return parse_clock(s)


def parse_clock(s: str) -> float | None:
    """'01:00' -> 60.0 ; '1:02:03' -> 3723.0 ; '45.5' -> 45.5 ; invalide -> None."""
    try:
        total = 0.0
        for part in s.strip().split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return None


def parse_time_control(ti: str | None) -> tuple[float, float, float] | None:
    """TI[initial/incrément/prolongation] -> secondes (champs absents = 0)."""
    if not ti:
        return None
    parts = [parse_clock(p) if p.strip() else 0.0 for p in ti.split("/")]
    if not parts or parts[0] is None or any(p is None for p in parts):
        return None
    parts += [0.0] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def fmt_clock(sec: float) -> str:
    """75.4 -> '1:15' (arrondi à la seconde inférieure)."""
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def describe_type(ty: str | None) -> str:
    """'s8r14' -> 's8r14 (8×8, départ aléatoire à 14 pions)'."""
    if not ty:
        return ""
    m = re.fullmatch(r"s(\d+)r(\d+)", ty.strip())
    return f"{ty} ({m.group(1)}×{m.group(1)}, départ aléatoire à {m.group(2)} pions)" if m else ty


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s, flags=re.S)


def _parse_board(value: str) -> Board:
    """BO[8 <8 lignes de 8 cases> <joueur>] ; '*' noir, 'O' blanc, '-' vide."""
    s = "".join(value.split())
    m = re.fullmatch(r"(\d+)([*Oo\-.]{64})([*Oo])", s)
    if not m:
        raise ValueError("BO invalide (plateau 8x8 + joueur au trait attendus)")
    if m.group(1) != "8":
        raise ValueError(f"taille de plateau non supportée : {m.group(1)}")
    return Board(f"{m.group(2)} {m.group(3)}")


def _parse_one(body: str) -> GGFGame:
    props: dict[str, str] = {}
    seq: list[tuple[int, str, float | None, float | None]] = []  # couleur, coup, éval, temps
    for name, raw in _PROP.findall(body):
        name, value = name.upper(), _unescape(raw)
        if name in ("B", "W"):
            f = value.split("/")
            f += [""] * (3 - len(f))
            seq.append((BLACK if name == "B" else WHITE, f[0].strip(), _num(f[1]), _num(f[2])))
        else:
            props.setdefault(name, value)

    gm = props.get("GM", "Othello")
    if gm.lower() != "othello":
        raise ValueError(f"jeu non supporté : {gm!r}")
    start = _parse_board(props["BO"]) if "BO" in props else Board()

    board, moves, scores, times = start.copy(), [], [], []
    for n, (color, tok, sc, tm) in enumerate(seq, 1):
        label = f"coup {n} ({'B' if color == BLACK else 'W'}[{tok}])"
        try:
            x = PASS if tok.lower() in ("pa", "pass") else str_to_sq(tok)
        except ValueError as e:
            raise ValueError(f"{label} : {e}") from None
        if board.player != color:
            if x != PASS and board.must_pass():    # passe implicite
                board.make_move(PASS)
                moves.append(PASS)
                scores.append(None)
                times.append(None)
            else:
                raise ValueError(f"{label} : ce n'est pas au tour de cette couleur")
        try:
            board.make_move(x)
        except ValueError as e:                    # IllegalMoveError
            raise ValueError(f"{label} : {e}") from None
        moves.append(x)
        scores.append(sc)
        times.append(tm)
    return GGFGame(start, moves, props, scores, times)


def parse_ggf(text: str) -> list[GGFGame]:
    """Toutes les parties d'un texte GGF (fichier ou presse-papiers)."""
    bodies = _GAME.findall(text)
    if not bodies:
        raise ValueError("aucune partie GGF trouvée (« (;GM[Othello]... ;) » attendu)")
    return [_parse_one(b) for b in bodies]


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("]", "\\]")


def to_ggf(start: Board, moves: list[int], black: str = "Black", white: str = "White",
           place: str = "othello_gui", scores: list[float | None] | None = None,
           times: list[float | None] | None = None,
           meta: dict[str, str] | None = None) -> str:
    """Sérialise une partie (départ + coups, PASS inclus) en GGF.

    scores/times : listes alignées sur `moves` (None = absent) ; écrites B[E7/éval/temps].
    meta : propriétés à conserver (PC, DT, RB, RW, TI, TY)."""
    meta = meta or {}
    cells, player = start.to_string().split()
    rows = "\n".join(cells[i:i + 8] for i in range(0, 64, 8))

    b = start.copy()
    toks = []
    for i, m in enumerate(moves):
        c = "B" if b.player == BLACK else "W"
        f = ["PA" if m == PASS else sq_to_str(m).upper()]
        sc = scores[i] if scores and i < len(scores) else None
        tm = times[i] if times and i < len(times) else None
        if sc is not None or tm is not None:
            f.append("" if sc is None else f"{sc:.2f}")
        if tm is not None:
            f.append(f"{tm:.2f}")
        toks.append(f"{c}[{'/'.join(f)}]")
        b.make_move(m)
    lines = ["".join(toks[i:i + 2]) for i in range(0, len(toks), 2)]

    re_ = "?"
    if b.is_game_over():
        nb, nw = b.n_discs
        if nb > nw:
            nb += b.n_empties
        elif nw > nb:
            nw += b.n_empties
        re_ = f"{nb - nw:+d}"

    dt = meta.get("DT") or datetime.now(timezone.utc).strftime("%Y.%m.%d_%H:%M:%S.UTC")
    opt = "".join(f"{k}[{_esc(meta[k])}]" for k in ("RB", "RW", "TI", "TY") if k in meta)
    head = (f"(;GM[Othello]PC[{_esc(meta.get('PC', place))}]DT[{_esc(dt)}]\n"
            f"PB[{_esc(black)}]PW[{_esc(white)}]\n" + (opt + "\n" if opt else "") +
            f"RE[{re_}]\nBO[8\n{rows}\n{player}]\n")
    return head + "\n".join(lines) + ";)\n"
