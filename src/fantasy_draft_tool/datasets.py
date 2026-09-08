"""Build a real player pool from free public data.

Two sources, both free and unauthenticated:

* **ADP** — Fantasy Football Calculator's public API
  (``https://fantasyfootballcalculator.com/api/v1/adp/{scoring}``). Aggregate
  average draft position from thousands of mock/real drafts.
* **Historical stats** — nflverse-data seasonal player stats
  (``stats_player_reg_{year}.csv`` release asset). Regular-season totals per
  player per season, including ``fantasy_points`` (standard) and
  ``fantasy_points_ppr``.

``build_dataset`` merges the last N seasons of stats with current ADP into one
row per player and derives a transparent ``projected_points`` proxy: a
recency-weighted per-game average projected over a 17-game season. It is a proxy,
not a projection service — swap in real projections later by writing the same
columns.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable

import pandas as pd
import requests

from .league import normalize_position

ADP_API = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"
NFLVERSE_STATS = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_reg_{year}.csv"
)
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

# Recency weights for the per-game average: most recent season counts most.
SEASON_WEIGHTS = [3.0, 2.0, 1.0]

# Positions with no usable history in the offensive stat feed — always priced
# off ADP rank, never off past fantasy points.
_ADP_ONLY_POSITIONS = {"K", "DEF"}

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


def _weighted_ppg(ppg_by_season: dict[int, float], seasons: list[int]) -> float:
    num = den = 0.0
    for weight, season in zip(SEASON_WEIGHTS, seasons):
        if season in ppg_by_season:
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
) -> pd.DataFrame:
    """Merge N seasons of stats with current ADP into one row per player."""
    seasons = sorted(stat_years, reverse=True)  # most recent first
    points_col = _points_column(scoring)

    stats = pd.concat(
        [fetch_seasonal_stats(y, read_csv=read_csv) for y in seasons],
        ignore_index=True,
    )
    adp = fetch_adp(adp_year, scoring=scoring, teams=teams, get_json=get_json)

    keys = set(stats["key"]) | (set(adp["key"]) if not adp.empty else set())
    stats_by_key = {k: g for k, g in stats.groupby("key")}
    adp_by_key = {r["key"]: r for _, r in adp.iterrows()} if not adp.empty else {}

    # Positional ADP rank, for the no-stats fallback.
    adp_pos_rank: dict[str, int] = {}
    if not adp.empty:
        for pos, grp in adp.sort_values("adp").groupby("position"):
            for i, key in enumerate(grp["key"], start=1):
                adp_pos_rank[key] = i

    rows = []
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

        avg_ppg = _weighted_ppg(ppg_by_season, seasons)
        if position in _ADP_ONLY_POSITIONS or avg_ppg <= 0:
            # Kickers and team defenses aren't in the offensive stat feed, and
            # rookies have no history: fall back to a low ADP-rank curve so their
            # value-over-replacement stays small.
            base, slope = _ADP_FALLBACK.get(position, (150.0, 5.0))
            proj = round(max(base - slope * adp_pos_rank.get(key, 60), 0.0), 1) if a is not None else 0.0
        else:
            proj = round(avg_ppg * 17, 1)

        recent, oldest = seasons[0], seasons[-1]
        row = {
            "player": name,
            "position": position,
            "team": team,
            "projected_points": proj,
            "avg_ppg_3yr": round(avg_ppg, 2),
            "adp": round(float(a["adp"]), 1) if a is not None else "",
            "adp_stdev": round(float(a["adp_stdev"]), 1) if a is not None else "",
            "times_drafted": int(a["times_drafted"]) if a is not None else "",
            "bye": (a["bye"] if a is not None and pd.notna(a["bye"]) else ""),
            "ppg_trend": round(ppg_by_season.get(recent, 0.0) - ppg_by_season.get(oldest, 0.0), 2),
        }
        for s in seasons:
            row[f"points_{s}"] = round(pts_by_season.get(s, 0.0), 1)
            row[f"games_{s}"] = games_by_season.get(s, 0)
        rows.append(row)

    df = pd.DataFrame(rows)
    # Drop noise: players with neither a projection nor an ADP (practice-squad
    # bodies, backup kickers) — they only distort replacement levels.
    keep = (df["projected_points"] > 0) | (df["adp"].astype(str) != "")
    df = df[keep]
    return df.sort_values("projected_points", ascending=False).reset_index(drop=True)
