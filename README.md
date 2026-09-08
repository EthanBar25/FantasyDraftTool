# FantasyDraftTool

A personal tool to help with fantasy NFL drafts — turn player projections into
draft rankings and make faster, better picks on draft day.

## Status

Working today:

- **Draft board web app** (`fantasy-draft serve`) — a Sleeper-style rounds × teams
  grid. Enter every pick for every team, get a live recommendation panel for the
  pick on the clock, and track your roster. State is saved to disk so a refresh
  or restart mid-draft doesn't lose the board.
- **Sleeper import** — paste a league ID, a draft ID, or a **mock draft ID** to
  pull in scoring rules, roster slots, team count, and picks already made. For a
  mock draft the rules are rebuilt from the draft itself. **Sync draft** then
  re-pulls picks as the (mock) draft runs, so you can dry-run the tool live.
- **Real player data** (`fantasy-draft fetch-data`) — pulls current ADP (Fantasy
  Football Calculator) and the last three seasons of stats (nflverse) into
  `data/player_pool.csv`, which the board and `rank` then use automatically. See
  [`data/SOURCES.md`](data/SOURCES.md).
- `rank` command: rank players by **value over replacement (VOR)** — how much a
  player scores above a freely-available replacement at the position.

Recommendations combine VOR with your roster needs, positional runs since your
last pick, tier cliffs, and value vs. ADP.

Planned:

- Score raw stat projections through the imported Sleeper scoring settings
- Real projections (not the recency-weighted proxy) from a projections source

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash);  .venv\Scripts\activate on PowerShell
pip install -e ".[dev]"
```

## Usage

### Draft board

```bash
fantasy-draft serve            # then open http://127.0.0.1:8000
```

- **League settings** — set team count, your draft slot, roster slots (Sleeper
  codes: `QB RB WR TE FLEX SUPER_FLEX K DEF BN`), and scoring as JSON.
- **Import from Sleeper**:
  - *Real league* — paste the League ID (the number in your league URL).
  - *Mock draft* — paste just the Draft ID from `sleeper.com/draft/nfl/<id>`,
    leave League ID blank. Add your Sleeper username to set your slot automatically.
  - Once linked, **Sync draft** (and a background poll) pull new picks as they
    happen — draft in the Sleeper mock and watch the recommendations update.
- Click any board cell to search and set that pick; click a recommendation to
  assign it to the pick on the clock.

### Player data

```bash
fantasy-draft fetch-data                       # ADP 2026 + stats 2023-2025, half-PPR
fantasy-draft fetch-data --scoring ppr --teams 10
```

Writes `data/player_pool.csv`. Needs network; nothing else does.

### Rankings CLI

```bash
fantasy-draft rank -n 40           # uses data/player_pool.csv if present, else the sample
fantasy-draft rank data/sample_players.csv
```

### Projections CSV format

Required columns (case-insensitive): `player`, `position`, `team`,
`projected_points`. Extra columns are ignored. Put your own files in `data/`
(git-ignored except the sample) — see [`data/README.md`](data/README.md).

## Development

```bash
pytest        # run tests
ruff check .  # lint
```

## Project layout

```
src/fantasy_draft_tool/
  league.py      # LeagueSettings, modeled on Sleeper (scoring, roster slots)
  draft.py       # snake pick order, board state, per-team rosters
  rankings.py    # load projections, compute VOR
  recommend.py   # VOR + roster need + positional runs + ADP value -> recommendations
  datasets.py    # fetch + merge ADP and 3-year stats into player_pool.csv
  sleeper.py     # read-only Sleeper API client: league / draft / mock-draft import + live sync
  session.py     # in-memory draft session, persisted to data/draft_session.json
  cli.py         # `fantasy-draft` command (rank, serve)
  web/           # FastAPI app + vanilla-JS draft board (static/)
tests/           # pytest suite
data/            # projection files (sample checked in, rest ignored)
```

## License

MIT — see [LICENSE](LICENSE).
