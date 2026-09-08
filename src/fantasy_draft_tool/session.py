"""A single in-memory draft session, persisted to disk so a restart or a browser
refresh mid-draft doesn't lose your board.
"""

from __future__ import annotations

import json
from pathlib import Path

from .draft import DraftState
from .league import LeagueSettings, normalize_position
from .rankings import RankedPlayer, rank_from_csv
from .recommend import Recommendation, available_players, recommend
from .sleeper import SleeperClient, apply_import

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
PLAYER_POOL = DATA_DIR / "player_pool.csv"
SAMPLE_PLAYERS = DATA_DIR / "sample_players.csv"
DEFAULT_SESSION_FILE = DATA_DIR / "draft_session.json"


def default_projections() -> Path:
    """Prefer the fetched real dataset; fall back to the bundled sample."""
    return PLAYER_POOL if PLAYER_POOL.exists() else SAMPLE_PLAYERS


class DraftSession:
    def __init__(
        self,
        projections_path: Path | str | None = None,
        session_file: Path | str = DEFAULT_SESSION_FILE,
    ) -> None:
        self.projections_path = Path(projections_path) if projections_path else default_projections()
        self.session_file = Path(session_file)
        self.league = LeagueSettings()
        self.state = DraftState(self.league, my_slot=1)
        self.slot_labels: dict[int, str] = {}
        self._pool: list[RankedPlayer] = []
        self._rerank()

    # -- projections / pool -------------------------------------------

    def _rerank(self) -> None:
        self._pool = rank_from_csv(self.projections_path, self.league.replacement_ranks())

    @property
    def pool(self) -> list[RankedPlayer]:
        return self._pool

    def find_player(self, name: str) -> RankedPlayer | None:
        key = name.strip().lower()
        for p in self._pool:
            if p.player.lower() == key:
                return p
        return None

    def search_players(self, query: str, limit: int = 12, only_available: bool = True):
        q = query.strip().lower()
        drafted = self.state.drafted_names()
        rows = []
        for p in sorted(self._pool, key=lambda x: x.vor, reverse=True):
            if q and q not in p.player.lower() and q != p.position.lower():
                continue
            is_drafted = p.player.lower() in drafted
            if only_available and is_drafted:
                continue
            rows.append(
                {
                    "player": p.player,
                    "position": p.position,
                    "team": p.team,
                    "projected_points": round(p.projected_points, 1),
                    "vor": round(p.vor, 1),
                    "adp": round(p.adp, 1) if p.adp is not None else None,
                    "drafted": is_drafted,
                }
            )
            if len(rows) >= limit:
                break
        return rows

    # -- mutations --------------------------------------------------

    def set_league(self, league: LeagueSettings, my_slot: int | None = None) -> None:
        self.league = league
        self.state.reconfigure(league, my_slot=my_slot)
        self._rerank()
        self.save()

    def set_my_slot(self, slot: int) -> None:
        self.state.my_slot = max(1, min(slot, self.league.num_teams))
        self.save()

    def set_pick(self, pick_no: int, player: str, position: str = "", team: str | None = None,
                 player_id: str | None = None) -> None:
        if not position:
            found = self.find_player(player)
            if found:
                position, team = found.position, team or found.team
        self.state.set_pick(pick_no, player=player, position=normalize_position(position or "NA"),
                            team=team, player_id=player_id)
        self.save()

    def clear_pick(self, pick_no: int) -> None:
        self.state.clear_pick(pick_no)
        self.save()

    def reset(self) -> None:
        self.state.reset()
        self.save()

    def import_sleeper(self, league_id: str | None, draft_id: str | None,
                       my_slot: int | None = None, client: SleeperClient | None = None) -> None:
        client = client or SleeperClient()
        imported = client.import_league(league_id=league_id, draft_id=draft_id)
        apply_import(self.state, imported, my_slot=my_slot)
        self.league = self.state.league
        self.slot_labels = dict(imported.draft_slot_to_team)
        self._rerank()
        self.save()

    # -- views ----------------------------------------------------

    def recommendations(self, limit: int = 8) -> list[Recommendation]:
        return recommend(self.state, self._pool, limit=limit)

    def best_available(self, limit: int = 12):
        avail = sorted(available_players(self.state, self._pool), key=lambda p: p.vor, reverse=True)
        return [
            {
                "player": p.player,
                "position": p.position,
                "team": p.team,
                "projected_points": round(p.projected_points, 1),
                "vor": round(p.vor, 1),
                "adp": round(p.adp, 1) if p.adp is not None else None,
            }
            for p in avail[:limit]
        ]

    def to_dict(self) -> dict:
        cur = self.state.current_pick_no
        return {
            "league": self.league.to_dict(),
            "draft": {
                **self.state.to_dict(),
                "slot_labels": {str(k): v for k, v in self.slot_labels.items()},
                "my_upcoming_picks": self.state.my_upcoming_picks(),
                "picks_until_my_turn": self.state.picks_between_now_and_my_next(),
                "on_the_clock_slot": self.state.get_pick(cur).slot if cur else None,
            },
            "recommendations": [r.to_dict() for r in self.recommendations()],
            "best_available": self.best_available(),
        }

    # -- persistence --------------------------------------------

    def save(self) -> None:
        payload = {
            "projections_path": str(self.projections_path),
            "my_slot": self.state.my_slot,
            "slot_labels": {str(k): v for k, v in self.slot_labels.items()},
            "league": self.league.to_dict(),
            "picks": [p.to_dict() for p in self.state.picks if p.is_made],
        }
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.session_file.write_text(json.dumps(payload, indent=2))

    def load(self) -> bool:
        if not self.session_file.exists():
            return False
        data = json.loads(self.session_file.read_text())
        saved = data.get("projections_path")
        if saved and Path(saved).exists():
            self.projections_path = Path(saved)
        else:
            self.projections_path = default_projections()
        self.league = LeagueSettings.from_dict(data.get("league", {}))
        self.state = DraftState(self.league, my_slot=int(data.get("my_slot", 1)))
        self.slot_labels = {int(k): v for k, v in (data.get("slot_labels") or {}).items()}
        self._rerank()
        for p in data.get("picks", []):
            try:
                self.state.set_pick(
                    int(p["pick_no"]),
                    player=p["player"],
                    position=p.get("position") or "NA",
                    team=p.get("team"),
                    player_id=p.get("player_id"),
                )
            except (ValueError, KeyError, IndexError):
                continue
        return True
