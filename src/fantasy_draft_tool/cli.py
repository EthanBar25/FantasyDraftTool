"""Command-line entry point for FantasyDraftTool."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .rankings import rank_from_csv
from .session import PLAYER_POOL, default_projections


def _cmd_rank(args: argparse.Namespace) -> int:
    projections = args.projections or default_projections()
    players = rank_from_csv(projections)
    top = players[: args.limit]
    width = max((len(p.player) for p in top), default=6)
    print(f"source: {projections}")
    print(f"{'#':>3}  {'PLAYER':<{width}}  POS  TEAM   PROJ    VOR    ADP")
    for p in top:
        adp = f"{p.adp:>6.1f}" if p.adp is not None else "     -"
        print(
            f"{p.overall_rank:>3}  {p.player:<{width}}  {p.position:<3}  "
            f"{p.team or '':<4}  {p.projected_points:>6.1f}  {p.vor:>6.1f}  {adp}"
        )
    return 0


def _cmd_fetch_data(args: argparse.Namespace) -> int:
    from .datasets import build_dataset

    print(f"Fetching ADP ({args.scoring}, {args.teams}-team, {args.adp_year}) and "
          f"stats for {', '.join(map(str, args.years))} ...")
    df = build_dataset(
        stat_years=args.years,
        adp_year=args.adp_year,
        scoring=args.scoring,
        teams=args.teams,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    with_adp = int((df["adp"] != "").sum()) if "adp" in df.columns else 0
    print(f"Wrote {len(df)} players ({with_adp} with ADP) to {args.output}")
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
        nargs="?",
        default=None,
        help="Projections CSV (default: data/player_pool.csv if present, else the sample).",
    )
    rank.add_argument(
        "-n", "--limit", type=int, default=25, help="How many players to show (default: 25)."
    )
    rank.set_defaults(func=_cmd_rank)

    fetch = sub.add_parser(
        "fetch-data",
        help="Download ADP + last 3 seasons of stats into a player_pool.csv.",
    )
    fetch.add_argument(
        "--years", type=int, nargs="+", default=[2025, 2024, 2023],
        help="Stat seasons to pull (default: 2025 2024 2023).",
    )
    fetch.add_argument("--adp-year", type=int, default=2026, help="ADP season (default: 2026).")
    fetch.add_argument(
        "--scoring", default="half-ppr", choices=["standard", "half-ppr", "ppr"],
        help="Scoring format for points and ADP (default: half-ppr).",
    )
    fetch.add_argument("--teams", type=int, default=12, help="League size for ADP (default: 12).")
    fetch.add_argument("-o", "--output", type=Path, default=PLAYER_POOL, help="Output CSV path.")
    fetch.set_defaults(func=_cmd_fetch_data)

    serve = sub.add_parser("serve", help="Run the local draft-board web app.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)
    return parser


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "fantasy_draft_tool.web.app:app", host=args.host, port=args.port, reload=False
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
