# FantasyDraftTool

A personal tool to help with fantasy NFL drafts — turn player projections into
draft rankings and make faster, better picks on draft day.

## Status

Early scaffold. Working today:

- `rank` command: load a projections CSV and rank players by **value over
  replacement (VOR)** — how much a player scores above a freely-available
  replacement at the same position.

Planned:

- ADP integration and "reach vs. value" flags
- Live draft board: track picks, show best available by roster need
- League-settings-aware scoring (PPR, superflex, roster slots)
- Projection scrapers / importers for common sources

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash);  .venv\Scripts\activate on PowerShell
pip install -e ".[dev]"
```

## Usage

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
  rankings.py   # load projections, compute VOR
  cli.py        # `fantasy-draft` command
tests/          # pytest suite
data/           # projection files (sample checked in, rest ignored)
```

## License

MIT — see [LICENSE](LICENSE).
