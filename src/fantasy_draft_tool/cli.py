"""Command-line entry point for FantasyDraftTool."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .rankings import rank_from_csv


def _cmd_rank(args: argparse.Namespace) -> int:
    players = rank_from_csv(args.projections)
    top = players[: args.limit]
    width = max((len(p.player) for p in top), default=6)
    print(f"{'#':>3}  {'PLAYER':<{width}}  POS  TEAM   PROJ    VOR")
    for p in top:
        print(
            f"{p.overall_rank:>3}  {p.player:<{width}}  {p.position:<3}  "
            f"{p.team:<4}  {p.projected_points:>6.1f}  {p.vor:>6.1f}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fantasy-draft",
        description="Fantasy NFL draft prep and draft-day recommendations.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    rank = sub.add_parser("rank", help="Rank players by value over replacement (VOR).")
    rank.add_argument(
        "projections",
        type=Path,
        help="Path to a projections CSV (columns: player, position, team, projected_points).",
    )
    rank.add_argument(
        "-n", "--limit", type=int, default=25, help="How many players to show (default: 25)."
    )
    rank.set_defaults(func=_cmd_rank)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
