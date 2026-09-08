# FantasyDraftTool

A personal tool to help with fantasy NFL drafts — turn player projections into
draft rankings and make faster, better picks on draft day.

## Status

Working today:

- **Draft board web app** (`fantasy-draft serve`) — a Sleeper-style rounds × teams
  grid. Enter every pick for every team, get a live recommendation panel for the
  pick on the clock, and track your roster. State is saved to disk so a refresh
  or restart mid-draft doesn't lose the board.
- **Sleeper import** — paste a league ID (and/or draft ID) to pull in scoring
  rules, roster slots, team count, and any picks already made.
- `rank` command: rank a projections CSV by **value over replacement (VOR)** —
  how much a player scores above a freely-available replacement at the position.

Recommendations combine VOR with your roster needs, positional runs since your
last pick, and tier cliffs.

Planned:

- ADP integration and "reach vs. value" flags
- Score raw stat projections through the imported Sleeper scoring settings
- Projection scrapers / importers for common sources

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
- **Import from Sleeper** — paste your league ID (the number in the league URL)
  and optionally a draft ID.
- Click any board cell to search and set that pick; click a recommendation to
  assign it to the pick on the clock.

### Rankings CLI

```bash
# Top 25 by VOR from the bundled sample data
fantasy-draft rank data/sample_players.csv

# Or without installing the script
python -m fantasy_draft_tool rank data/sample_players.csv -n 40
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
  recommend.py   # VOR + roster need + positional runs -> pick recommendations
  sleeper.py     # read-only Sleeper API client + league/pick import
  session.py     # in-memory draft session, persisted to data/draft_session.json
  cli.py         # `fantasy-draft` command (rank, serve)
  web/           # FastAPI app + vanilla-JS draft board (static/)
tests/           # pytest suite
data/            # projection files (sample checked in, rest ignored)
```

## License

MIT — see [LICENSE](LICENSE).
