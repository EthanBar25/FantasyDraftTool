"""Load player projections and turn them into draft rankings.

The core idea for a draft tool is *value over replacement* (VOR): a player is
only worth what they give you above a freely-available replacement at the same
position. This module loads a projections CSV and computes VOR-based rankings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .league import normalize_position

# Roughly how many players at each position come off the board before the talent
# drops to "waiver wire" level in a 12-team league. Tune to your league.
DEFAULT_REPLACEMENT_RANK: dict[str, int] = {
    "QB": 14,
    "RB": 30,
    "WR": 36,
    "TE": 14,
    "K": 12,
    "DEF": 12,
}

REQUIRED_COLUMNS = {"player", "position", "team", "projected_points"}


@dataclass(frozen=True)
class RankedPlayer:
    player: str
    position: str
    team: str
    projected_points: float
    vor: float
    overall_rank: int
    position_rank: int
    adp: float | None = None


def load_projections(path: str | Path) -> pd.DataFrame:
    """Read a projections CSV and validate it has the columns we need."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"{path}: missing required column(s): {', '.join(sorted(missing))}"
        )
    df["position"] = df["position"].map(normalize_position)
    df["projected_points"] = pd.to_numeric(df["projected_points"], errors="coerce")
    if "adp" in df.columns:
        df["adp"] = pd.to_numeric(df["adp"], errors="coerce")
    df = df.dropna(subset=["projected_points"])
    # A player projected for nothing isn't a draftable "replacement"; keeping
    # them would drag every replacement level toward zero.
    df = df[df["projected_points"] > 0]
    return df.reset_index(drop=True)


def compute_vor(
    df: pd.DataFrame,
    replacement_rank: dict[str, int] | None = None,
) -> list[RankedPlayer]:
    """Compute value over replacement and return players sorted by VOR desc."""
    replacement_rank = replacement_rank or DEFAULT_REPLACEMENT_RANK
    rows: list[RankedPlayer] = []

    for position, group in df.groupby("position"):
        ordered = group.sort_values("projected_points", ascending=False).reset_index(drop=True)
        cutoff = replacement_rank.get(position, len(ordered))
        # Replacement value = the Nth-best projection at the position.
        idx = min(cutoff, len(ordered)) - 1
        replacement_points = float(ordered.loc[max(idx, 0), "projected_points"])

        for pos_rank, row in enumerate(ordered.itertuples(index=False), start=1):
            adp = getattr(row, "adp", None)
            rows.append(
                RankedPlayer(
                    player=row.player,
                    position=position,
                    team=row.team,
                    projected_points=float(row.projected_points),
                    vor=float(row.projected_points) - replacement_points,
                    overall_rank=0,  # filled in below
                    position_rank=pos_rank,
                    adp=float(adp) if adp is not None and pd.notna(adp) else None,
                )
            )

    rows.sort(key=lambda r: r.vor, reverse=True)
    return [
        RankedPlayer(**{**r.__dict__, "overall_rank": i})
        for i, r in enumerate(rows, start=1)
    ]


def rank_from_csv(
    path: str | Path,
    replacement_rank: dict[str, int] | None = None,
) -> list[RankedPlayer]:
    """Convenience: load a CSV and return VOR-ranked players."""
    return compute_vor(load_projections(path), replacement_rank)
