# Data sources

`player_pool.csv` is **built**, not hand-maintained. Regenerate it with:

```bash
fantasy-draft fetch-data              # ADP 2026, stats 2023-2025, half-PPR, 12-team
fantasy-draft fetch-data --scoring ppr --teams 10 --adp-year 2026
```

## ADP — Fantasy Football Calculator

<https://fantasyfootballcalculator.com/adp> · public API
`https://fantasyfootballcalculator.com/api/v1/adp/{standard|half-ppr|ppr}?teams=N&year=YYYY`

Aggregate average draft position from many drafts. Free, no key. We store `adp`,
`adp_stdev`, `times_drafted`, and `bye`.

## Historical stats — nflverse

<https://github.com/nflverse/nflverse-data> · release `stats_player`,
asset `stats_player_reg_{year}.csv` (regular-season totals per player per season).
Released under the [nflverse data license](https://github.com/nflverse/nflverse-data)
(CC-BY-4.0). We store `fantasy_points` (standard) and `fantasy_points_ppr`, from
which half-PPR is the mean, plus games played.

## Derived columns

| column | meaning |
|---|---|
| `points_YYYY`, `games_YYYY` | that season's fantasy points (chosen scoring) and games |
| `avg_ppg_3yr` | per-game average, weighted 3× / 2× / 1× from newest to oldest season |
| `projected_points` | `avg_ppg_3yr × 17` — a transparent proxy, **not** a projection service |
| `ppg_trend` | newest-season PPG minus oldest-season PPG |

Players with ADP but no stats (kickers, team defenses, rookies) get a rough
ADP-rank-based `projected_points` so they still slot onto the board.
