"""Build a real player pool from free public data.

Three sources, all free and unauthenticated:

* **ADP** — Fantasy Football Calculator's public API
  (``https://fantasyfootballcalculator.com/api/v1/adp/{scoring}``). Aggregate
  average draft position from thousands of mock/real drafts, for the *current*
  ``adp_year`` — this is the tool's only signal for this year's market view
  (new team, coaching change, depth-chart battle, injury recovery, rookie hype)
  since the stats below are always backward-looking.
* **Historical stats** — nflverse-data seasonal player stats
  (``stats_player_reg_{year}.csv`` release asset). Regular-season totals per
  player per season, including ``fantasy_points`` (standard) and
  ``fantasy_points_ppr``.
* **Player status** — Sleeper's public player catalog
  (``https://api.sleeper.app/v1/players/nfl``, the same source
  :mod:`fantasy_draft_tool.sleeper` already reads picks from). Current
  injury/suspension designations — real-world news neither of the above can see.

``build_dataset`` merges the last N seasons of stats with current ADP and
status into one row per player. ``projected_points`` is a transparent proxy,
not a projection service — swap in real projections later by writing the same
columns. For a player with usable history *and* a current ADP, it blends a
recency-weighted per-game average (projected over 17 games) with an
"ADP-implied" value — see ``ADP_BLEND_WEIGHT`` — so this year's draft market
carries real weight, not just last year's box scores. Players with no history
(rookies, K/DEF) are still priced purely off ADP rank.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable
from pathlib import Path

import pandas as pd
import requests

from .league import normalize_position

ADP_API = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"
NFLVERSE_STATS = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_reg_{year}.csv"
)
SLEEPER_PLAYERS_API = "https://api.sleeper.app/v1/players/nfl"
USER_AGENT = "FantasyDraftTool/0.1 (+https://github.com/EthanBar25/FantasyDraftTool)"

SCORING_ALIASES = {
    "standard": "standard",
    "std": "standard",
    "ppr": "ppr",
    "half": "half-ppr",
    "half-ppr": "half-ppr",
    "halfppr": "half-ppr",
}

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

# Recency weights for the per-game average, newest season first: last season
# carries most of the signal (role changes, breakouts, decline), the one before
# smooths single-season noise (TD variance), and the oldest is a light tiebreaker.
SEASON_WEIGHTS = [0.7, 0.2, 0.1]

# A season with fewer games than this has its weight scaled by games / this,
# so a 3-game sample can't dominate a player's per-game average. A 0-game
# season contributes nothing.
FULL_WEIGHT_GAMES = 8

# Positions with no usable history in the offensive stat feed — always priced
# off ADP rank, never off past fantasy points.
_ADP_ONLY_POSITIONS = {"K", "DEF"}

# For a player with both a stats-based proxy and a current-year ADP, how much
# of the final projection comes from this year's market vs. their own
# recency-weighted history. History captures a proven track record but can't
# see this year's news (an injury recovery, a new team, a camp battle won or
# lost) the way thousands of live ADP drafts already have. 0.5 gives the
# market a real, visible say without discarding a player's own production.
ADP_BLEND_WEIGHT = 0.5

# FFC's ADP endpoint only aggregates drafts from a short, recent window, so out
# of draft season it returns a handful of players (or none). Below this many
# players the live feed is treated as too thin to trust.
MIN_ADP_PLAYERS = 100

# Fallback projected points = ``base - slope * positional_ADP_rank``. K/DEF sit in
# a deliberately narrow, low band so their value-over-replacement stays near zero
# and they never crowd the top of the board; rookies get a fuller curve.
_ADP_FALLBACK = {
    "K": (26.0, 0.8),
    "DEF": (24.0, 0.7),
    "QB": (295.0, 6.0),
    "RB": (250.0, 5.0),
    "WR": (240.0, 4.5),
    "TE": (180.0, 4.0),
}

JsonGetter = Callable[[str], object]
CsvReader = Callable[[str], pd.DataFrame]


# -- fetch helpers ---------------------------------------------------------

def _http_get_json(url: str) -> object:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _http_get_csv(url: str) -> pd.DataFrame:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm_name(name: str) -> str:
    """Lowercase, drop punctuation and generational suffixes (Jr/III/...).

    Sources disagree on suffixes: FFC has "James Cook III", nflverse "James Cook".
    """
    tokens = str(name).lower().replace(".", "").replace("'", "").split()
    tokens = [t for t in tokens if t not in _NAME_SUFFIXES]
    return " ".join(tokens)


def _norm_pos(value: object) -> str:
    return normalize_position(value) if isinstance(value, str) and value.strip() else "NA"


# -- ADP -----------------------------------------------------------------

def fetch_adp(
    year: int,
    scoring: str = "half-ppr",
    teams: int = 12,
    *,
    get_json: JsonGetter | None = None,
) -> pd.DataFrame:
    """Return one row per player with average draft position for ``year``."""
    scoring = SCORING_ALIASES.get(scoring.lower(), scoring.lower())
    get_json = get_json or _http_get_json
    url = f"{ADP_API.format(scoring=scoring)}?teams={teams}&year={year}"
    payload = get_json(url)
    players = payload.get("players", []) if isinstance(payload, dict) else []
    rows = [
        {
            "player": p["name"],
            "position": _norm_pos(p.get("position", "")),
            "adp_team": (p.get("team") or "").upper() or None,
            "adp": float(p["adp"]),
            "adp_stdev": float(p.get("stdev", 0) or 0),
            "times_drafted": int(p.get("times_drafted", 0) or 0),
            "bye": p.get("bye"),
        }
        for p in players
        if p.get("name") and p.get("adp") is not None
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["key"] = df["player"].map(_norm_name) + "|" + df["position"]
    return df


def load_adp_snapshot(path: str | Path) -> pd.DataFrame:
    """Read the ADP columns of a previously built ``player_pool.csv`` back into
    the same shape :func:`fetch_adp` returns.

    Used as a last-known-good fallback: FFC's API only aggregates drafts from a
    short recent window, so outside draft season it returns few or no players.
    Returns an empty frame if the file is missing or has no ADP column.
    """
    path = Path(path)
    if not path.is_file():
        return pd.DataFrame()
    pool = pd.read_csv(path)
    if "adp" not in pool.columns:
        return pd.DataFrame()
    pool["adp"] = pd.to_numeric(pool["adp"], errors="coerce")
    pool = pool[pool["adp"].notna()]
    if pool.empty:
        return pd.DataFrame()

    def col(name: str, default: object) -> pd.Series:
        return pool[name] if name in pool.columns else pd.Series(default, index=pool.index)

    df = pd.DataFrame(
        {
            "player": pool["player"],
            "position": pool["position"].map(_norm_pos),
            "adp_team": col("team", None).where(col("team", None).notna(), None),
            "adp": pool["adp"].astype(float),
            "adp_stdev": pd.to_numeric(col("adp_stdev", 0.0), errors="coerce").fillna(0.0),
            "times_drafted": pd.to_numeric(col("times_drafted", 0), errors="coerce").fillna(0).astype(int),
            "bye": col("bye", None).where(col("bye", None).notna(), None),
        }
    ).reset_index(drop=True)
    df["key"] = df["player"].map(_norm_name) + "|" + df["position"]
    return df


# -- player status (injuries / suspensions) -------------------------------

def fetch_player_status(*, get_json: JsonGetter | None = None) -> pd.DataFrame:
    """Return one row per NFL player with their current availability status.

    Pulled from Sleeper's public player catalog — free, unauthenticated, and
    refreshed daily during the season. ``injury_status`` is Sleeper's own
    designation (``Questionable``/``Doubtful``/``Out``/``IR``/``PUP``/
    ``Suspended``/...); ``status`` is the roster status (``Active``,
    ``Inactive``, ``Injured Reserve``, ``Suspended``, ...). This is the only
    real-world-news signal in the dataset — everything else here is either
    past performance or the draft market.
    """
    get_json = get_json or _http_get_json
    payload = get_json(SLEEPER_PLAYERS_API)
    rows = []
    for p in (payload or {}).values():
        if not isinstance(p, dict):
            continue
        name = p.get("full_name") or " ".join(
            t for t in (p.get("first_name"), p.get("last_name")) if t
        )
        fantasy_positions = p.get("fantasy_positions") or []
        position = _norm_pos(p.get("position") or (fantasy_positions[0] if fantasy_positions else ""))
        if not name or position == "NA":
            continue
        rows.append(
            {
                "player": name,
                "position": position,
                "status": p.get("status") or "",
                "injury_status": p.get("injury_status") or "",
                "injury_note": p.get("injury_notes") or p.get("injury_body_part") or "",
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["key"] = df["player"].map(_norm_name) + "|" + df["position"]
        # Sleeper's catalog has retired/practice-squad duplicates under the
        # same name+position; prefer whichever row actually has signal.
        has_signal = (df["injury_status"] != "") | (df["status"] == "Active")
        df = (
            df.assign(_has_signal=has_signal)
            .sort_values("_has_signal", ascending=False)
            .drop_duplicates("key")
            .drop(columns="_has_signal")
        )
    return df


# -- seasonal stats -----------------------------------------------------

_STAT_COLUMNS = {
    "player_display_name": "player",
    "position": "position",
    "recent_team": "team",
    "games": "games",
    "fantasy_points": "points_std",
    "fantasy_points_ppr": "points_ppr",
    "passing_yards": "pass_yds",
    "passing_tds": "pass_td",
    "carries": "carries",
    "rushing_yards": "rush_yds",
    "rushing_tds": "rush_td",
    "receptions": "rec",
    "receiving_yards": "rec_yds",
    "receiving_tds": "rec_td",
}


def fetch_seasonal_stats(
    year: int,
    *,
    read_csv: CsvReader | None = None,
) -> pd.DataFrame:
    """Return normalized regular-season totals for offensive/kicker players."""
    read_csv = read_csv or _http_get_csv
    raw = read_csv(NFLVERSE_STATS.format(year=year))
    have = {src: dst for src, dst in _STAT_COLUMNS.items() if src in raw.columns}
    df = raw[list(have)].rename(columns=have).copy()
    df["position"] = df["position"].map(_norm_pos)
    df = df[df["position"].isin(SKILL_POSITIONS)]
    df["season"] = year
    for col in ("points_std", "points_ppr", "games"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["points_half"] = (df.get("points_std", 0.0) + df.get("points_ppr", 0.0)) / 2.0
    df["key"] = df["player"].map(_norm_name) + "|" + df["position"]
    return df.reset_index(drop=True)


# -- merge ------------------------------------------------------------

def _points_column(scoring: str) -> str:
    return {
        "standard": "points_std",
        "ppr": "points_ppr",
        "half-ppr": "points_half",
    }.get(SCORING_ALIASES.get(scoring.lower(), scoring.lower()), "points_half")


def _weighted_ppg(
    ppg_by_season: dict[int, float],
    seasons: list[int],
    games_by_season: dict[int, int] | None = None,
) -> float:
    """Recency-weighted per-game average over ``seasons`` (newest first).

    Seasons with fewer than ``FULL_WEIGHT_GAMES`` games are down-weighted in
    proportion to games played; weights renormalize over what's left.
    """
    num = den = 0.0
    for weight, season in zip(SEASON_WEIGHTS, seasons):
        if season in ppg_by_season:
            if games_by_season is not None:
                games = games_by_season.get(season, 0)
                weight *= min(games, FULL_WEIGHT_GAMES) / FULL_WEIGHT_GAMES
            num += weight * ppg_by_season[season]
            den += weight
    return num / den if den else 0.0


def build_dataset(
    stat_years: Iterable[int],
    adp_year: int,
    scoring: str = "half-ppr",
    teams: int = 12,
    *,
    get_json: JsonGetter | None = None,
    read_csv: CsvReader | None = None,
    get_status_json: JsonGetter | None = None,
    include_status: bool = True,
    adp_fallback: pd.DataFrame | None = None,
    min_adp_players: int = MIN_ADP_PLAYERS,
) -> pd.DataFrame:
    """Merge N seasons of stats with current ADP and player status into one
    row per player.

    If the live ADP feed returns fewer than ``min_adp_players`` players and
    ``adp_fallback`` (see :func:`load_adp_snapshot`) has more, the fallback is
    used instead. The returned frame's ``attrs["adp_source"]`` is ``"live"`` or
    ``"fallback"`` and ``attrs["live_adp_players"]`` is the live count.
    """
    seasons = sorted(stat_years, reverse=True)  # most recent first
    points_col = _points_column(scoring)

    stats = pd.concat(
        [fetch_seasonal_stats(y, read_csv=read_csv) for y in seasons],
        ignore_index=True,
    )
    adp = fetch_adp(adp_year, scoring=scoring, teams=teams, get_json=get_json)
    live_adp_players = len(adp)
    adp_source = "live"
    if (
        live_adp_players < min_adp_players
        and adp_fallback is not None
        and len(adp_fallback) > live_adp_players
    ):
        adp, adp_source = adp_fallback, "fallback"
    status = fetch_player_status(get_json=get_status_json) if include_status else pd.DataFrame()

    keys = set(stats["key"]) | (set(adp["key"]) if not adp.empty else set())
    stats_by_key = {k: g for k, g in stats.groupby("key")}
    adp_by_key = {r["key"]: r for _, r in adp.iterrows()} if not adp.empty else {}
    status_by_key = {r["key"]: r for _, r in status.iterrows()} if not status.empty else {}

    # Positional ADP rank, for the no-stats fallback and the blend below.
    adp_pos_rank: dict[str, int] = {}
    if not adp.empty:
        for pos, grp in adp.sort_values("adp").groupby("position"):
            for i, key in enumerate(grp["key"], start=1):
                adp_pos_rank[key] = i

    # -- pass 1: per-player history, independent of ADP -------------------
    prelim = []
    for key in sorted(keys):
        g = stats_by_key.get(key)
        a = adp_by_key.get(key)
        name = (g["player"].iloc[-1] if g is not None else a["player"])
        position = key.split("|", 1)[1]

        ppg_by_season, pts_by_season, games_by_season = {}, {}, {}
        if g is not None:
            for _, r in g.iterrows():
                s = int(r["season"])
                pts_by_season[s] = float(r.get(points_col, 0.0))
                games_by_season[s] = int(r.get("games", 0) or 0)
                ppg_by_season[s] = pts_by_season[s] / games_by_season[s] if games_by_season[s] else 0.0

        team = None
        if g is not None and pd.notna(g["team"].iloc[-1]):
            team = str(g["team"].iloc[-1])
        elif a is not None:
            team = a["adp_team"]

        avg_ppg = _weighted_ppg(ppg_by_season, seasons, games_by_season)
        stats_proj = round(avg_ppg * 17, 1) if avg_ppg > 0 else None

        prelim.append(
            {
                "key": key, "name": name, "position": position, "team": team, "a": a,
                "avg_ppg": avg_ppg, "stats_proj": stats_proj,
                "ppg_by_season": ppg_by_season, "pts_by_season": pts_by_season,
                "games_by_season": games_by_season,
            }
        )

    # This year's stats-only projection curve per position, best to worst —
    # what the "ADP-implied" value for a given positional ADP rank blends in.
    stats_curve_by_pos: dict[str, list[float]] = {}
    for row in prelim:
        if row["position"] not in _ADP_ONLY_POSITIONS and row["stats_proj"] is not None:
            stats_curve_by_pos.setdefault(row["position"], []).append(row["stats_proj"])
    for curve in stats_curve_by_pos.values():
        curve.sort(reverse=True)

    # -- pass 2: blend in this year's ADP, assemble rows -------------------
    rows = []
    for row in prelim:
        key, position, a = row["key"], row["position"], row["a"]
        stats_proj = row["stats_proj"]

        if position in _ADP_ONLY_POSITIONS or stats_proj is None:
            # Kickers and team defenses aren't in the offensive stat feed, and
            # rookies have no history: fall back to a low ADP-rank curve so their
            # value-over-replacement stays small.
            base, slope = _ADP_FALLBACK.get(position, (150.0, 5.0))
            proj = round(max(base - slope * adp_pos_rank.get(key, 60), 0.0), 1) if a is not None else 0.0
        elif a is not None:
            # Blend this year's market view in: price the player as if he were
            # the Nth-best at his position on paper, N = his current ADP rank.
            curve = stats_curve_by_pos.get(position) or [stats_proj]
            rank = adp_pos_rank.get(key, len(curve))
            adp_implied = curve[min(max(rank, 1), len(curve)) - 1]
            proj = round(ADP_BLEND_WEIGHT * adp_implied + (1 - ADP_BLEND_WEIGHT) * stats_proj, 1)
        else:
            # No current-year ADP at all (not in this year's draft pool) —
            # nothing to blend against, so go with pure history.
            proj = stats_proj

        st = status_by_key.get(key)
        ppg_by_season = row["ppg_by_season"]
        pts_by_season = row["pts_by_season"]
        games_by_season = row["games_by_season"]
        recent, oldest = seasons[0], seasons[-1]
        out = {
            "player": row["name"],
            "position": position,
            "team": row["team"],
            "projected_points": proj,
            "avg_ppg_3yr": round(row["avg_ppg"], 2),
            "adp": round(float(a["adp"]), 1) if a is not None else "",
            "adp_stdev": round(float(a["adp_stdev"]), 1) if a is not None else "",
            "times_drafted": int(a["times_drafted"]) if a is not None else "",
            "bye": (a["bye"] if a is not None and pd.notna(a["bye"]) else ""),
            "ppg_trend": round(ppg_by_season.get(recent, 0.0) - ppg_by_season.get(oldest, 0.0), 2),
            "status": st["status"] if st is not None else "",
            "injury_status": st["injury_status"] if st is not None else "",
            "injury_note": st["injury_note"] if st is not None else "",
        }
        for s in seasons:
            out[f"points_{s}"] = round(pts_by_season.get(s, 0.0), 1)
            out[f"games_{s}"] = games_by_season.get(s, 0)
        rows.append(out)

    df = pd.DataFrame(rows)
    # Drop noise: players with neither a projection nor an ADP (practice-squad
    # bodies, backup kickers) — they only distort replacement levels.
    keep = (df["projected_points"] > 0) | (df["adp"].astype(str) != "")
    df = df[keep]
    df = df.sort_values("projected_points", ascending=False).reset_index(drop=True)
    df.attrs["adp_source"] = adp_source
    df.attrs["live_adp_players"] = live_adp_players
    return df
