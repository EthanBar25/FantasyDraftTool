# data/

- `player_pool.csv` — the real player dataset: current ADP + the last three
  seasons of stats, merged into one row per player. **Built** by
  `fantasy-draft fetch-data`; see [SOURCES.md](SOURCES.md). The draft board and
  `fantasy-draft rank` use this automatically when it's present.
- `sample_players.csv` — a tiny checked-in example the tests run against.
- `draft_session.json` and anything else here is git-ignored (see `../.gitignore`).

## Projections CSV format

Required columns (case-insensitive): `player`, `position`, `team`,
`projected_points`. Optional: `adp` (used for value-vs-ADP hints). Extra columns
are ignored, so exports from most projection sites work after a light rename.
