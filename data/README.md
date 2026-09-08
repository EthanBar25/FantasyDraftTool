# data/

Put projection and ADP files here.

- `sample_players.csv` — a tiny checked-in example so the CLI and tests run out of the box.
- Everything else in this folder is git-ignored (see `../.gitignore`). Drop your
  full-season projection exports, ADP scrapes, and league settings here without
  worrying about committing large or licensed data.

## Projections CSV format

Required columns (case-insensitive): `player`, `position`, `team`, `projected_points`.
Extra columns are ignored, so exports from most projection sites work after a
light rename.
