# Data sources

`player_pool.csv` is **built**, not hand-maintained. Regenerate it with:

```bash
fantasy-draft fetch-data              # ADP 2026, stats 2023-2025, half-PPR, 12-team
fantasy-draft fetch-data --scoring ppr --teams 10 --adp-year 2026
fantasy-draft fetch-data --no-status  # skip the Sleeper injury/status pull
```

## ADP — Fantasy Football Calculator

<https://fantasyfootballcalculator.com/adp> · public API
`https://fantasyfootballcalculator.com/api/v1/adp/{standard|half-ppr|ppr}?teams=N&year=YYYY`

Aggregate average draft position from many drafts, for the **current** `adp_year`
— this is the tool's only read on this year's market (new team, coaching change,
camp battle, injury recovery, rookie hype), since the stats below are always
last year's (or older) box scores. Free, no key. We store `adp`, `adp_stdev`,
`times_drafted`, and `bye`.

## Historical stats — nflverse

<https://github.com/nflverse/nflverse-data> · release `stats_player`,
asset `stats_player_reg_{year}.csv` (regular-season totals per player per season).
Released under the [nflverse data license](https://github.com/nflverse/nflverse-data)
(CC-BY-4.0). We store `fantasy_points` (standard) and `fantasy_points_ppr`, from
which half-PPR is the mean, plus games played.

## Player status — Sleeper

<https://docs.sleeper.com/> · public API `https://api.sleeper.app/v1/players/nfl`
(the same source `sleeper.py` already reads draft picks from). Free, no key,
refreshed daily during the season. We store `status` (roster status, e.g.
`Active`/`Inactive`/`Injured Reserve`/`Suspended`) and `injury_status` (Sleeper's
designation, e.g. `Questionable`/`Doubtful`/`Out`/`IR`/`PUP`/`Suspended`) plus a
free-text `injury_note`. This is the tool's only real-world-**news** signal —
everything else here is either past performance or the draft market. It
deprioritizes recommendations (see below) rather than hiding players, since you
may still want to handcuff or stash someone.

## Derived columns

| column | meaning |
|---|---|
| `points_YYYY`, `games_YYYY` | that season's fantasy points (chosen scoring) and games |
| `avg_ppg_3yr` | per-game average, weighted 70% / 20% / 10% from newest to oldest season; a season with fewer than 8 games has its weight scaled by games / 8 (0 games → no weight), then weights renormalize |
| `projected_points` | see below — a transparent proxy, **not** a projection service |
| `ppg_trend` | newest-season PPG minus oldest-season PPG |

For a player with both usable history and a current-year ADP, `projected_points`
is a 50/50 blend (`ADP_BLEND_WEIGHT` in `datasets.py`) of `avg_ppg_3yr × 17` and
an **ADP-implied** value: the Nth-best stats-only projection at his position,
where N is his current positional ADP rank. That lets this year's market pull a
player's number toward what the market currently thinks he's worth, instead of
purely toward what he (or whoever previously held his role) scored in past
seasons. Players with ADP but no usable stats (kickers, team defenses, rookies)
still get a rough ADP-rank-based `projected_points`, unchanged, so they slot
onto the board; players with stats but no current-year ADP fall back to pure
history.
