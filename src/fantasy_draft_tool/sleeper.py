"""Read-only client for Sleeper's public API.

Docs: https://docs.sleeper.com/ — no auth needed for reads.

Handles three ways in:

* a **league id** — pulls scoring, roster slots, team count, and the league's draft;
* a **draft id** attached to a league — same, resolved via the draft;
* a **mock draft id** — a draft with no league. Roster slots and scoring are
  rebuilt from the draft's own ``settings``/``metadata`` so mocks work too.

``sync`` re-pulls just the picks so recommendations track a live (mock) draft.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from .draft import DraftState
from .league import DEFAULT_SCORING, LeagueSettings, normalize_position

API_BASE = "https://api.sleeper.app/v1"

GetJson = Callable[[str], Any]

# Sleeper draft `settings` slot keys -> our roster codes, in display order.
_SLOT_KEYS: list[tuple[str, str]] = [
    ("slots_qb", "QB"),
    ("slots_rb", "RB"),
    ("slots_wr", "WR"),
    ("slots_te", "TE"),
    ("slots_flex", "FLEX"),
    ("slots_wr_rb_flex", "WRRB_FLEX"),
    ("slots_rb_wr_flex", "WRRB_FLEX"),
    ("slots_wrrb_flex", "WRRB_FLEX"),
    ("slots_rec_flex", "REC_FLEX"),
    ("slots_super_flex", "SUPER_FLEX"),
    ("slots_k", "K"),
    ("slots_def", "DEF"),
    ("slots_dl", "DL"),
    ("slots_lb", "LB"),
    ("slots_db", "DB"),
    ("slots_idp_flex", "IDP_FLEX"),
    ("slots_bn", "BN"),
    ("slots_ir", "IR"),
    ("slots_reserve", "IR"),
    ("slots_taxi", "TAXI"),
]

# Sleeper `metadata.scoring_type` -> points per reception.
_PPR_BY_TYPE = {"std": 0.0, "standard": 0.0, "half_ppr": 0.5, "half-ppr": 0.5, "ppr": 1.0}


def _default_get_json(url: str) -> Any:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


@dataclass
class SleeperImport:
    league: LeagueSettings
    draft_id: str | None
    picks: list[dict]  # {pick_no, slot, player, position, team, player_id}
    draft_slot_to_team: dict[int, str]  # slot -> display name, best effort
    is_mock: bool = False
    status: str | None = None  # pre_draft | drafting | paused | complete
    my_slot: int | None = None  # resolved from `me`, when given
    league_id: str | None = None


class SleeperClient:
    def __init__(self, get_json: GetJson | None = None) -> None:
        self._get = get_json or _default_get_json

    def _url(self, *parts: str | int) -> str:
        return "/".join([API_BASE, *(str(p) for p in parts)])

    # -- raw endpoints --------------------------------------------------

    def get_league(self, league_id: str) -> dict:
        return self._get(self._url("league", league_id))

    def get_league_users(self, league_id: str) -> list[dict]:
        return self._get(self._url("league", league_id, "users")) or []

    def get_league_drafts(self, league_id: str) -> list[dict]:
        return self._get(self._url("league", league_id, "drafts")) or []

    def get_draft(self, draft_id: str) -> dict:
        return self._get(self._url("draft", draft_id))

    def get_draft_picks(self, draft_id: str) -> list[dict]:
        return self._get(self._url("draft", draft_id, "picks")) or []

    def get_user(self, username_or_id: str) -> dict:
        return self._get(self._url("user", username_or_id)) or {}

    # -- high level ---------------------------------------------------

    def import_league(
        self,
        league_id: str | None = None,
        draft_id: str | None = None,
        me: str | None = None,
    ) -> SleeperImport:
        """Build a :class:`SleeperImport` from a league id, a draft id, or both.

        ``me`` is an optional Sleeper username or user id; when it matches a
        drafter, the resulting ``my_slot`` is filled in.
        """
        if not league_id and not draft_id:
            raise ValueError("pass a league_id or a draft_id")

        league_data: dict = {}
        draft_data: dict = {}
        users: list[dict] = []

        if league_id:
            league_data = self.get_league(league_id) or {}
            users = self.get_league_users(league_id)
            if not draft_id:
                drafts = self.get_league_drafts(league_id)
                if drafts:
                    draft_id = drafts[0].get("draft_id")

        if draft_id:
            draft_data = self.get_draft(draft_id) or {}
            if not draft_data:
                raise ValueError(
                    f"Sleeper draft {draft_id} not found — check the ID from the draft URL"
                )
            resolved_league = draft_data.get("league_id")
            if not league_id and resolved_league:
                league_id = resolved_league
                league_data = self.get_league(league_id) or {}
                users = self.get_league_users(league_id)

        is_mock = draft_id is not None and not league_id
        settings = _league_from_payloads(league_data, draft_data)

        slot_to_team = _draft_slot_to_team(draft_data, users)
        picks_raw = self.get_draft_picks(draft_id) if draft_id else []
        picks = [_normalize_pick(p) for p in picks_raw]

        my_slot = self._resolve_slot(me, draft_data) if me else None

        return SleeperImport(
            league=settings,
            draft_id=draft_id,
            picks=picks,
            draft_slot_to_team=slot_to_team,
            is_mock=is_mock,
            status=draft_data.get("status"),
            my_slot=my_slot,
            league_id=league_id,
        )

    def sync_picks(self, draft_id: str) -> list[dict]:
        """Just the picks, normalized — for polling a live draft."""
        return [_normalize_pick(p) for p in self.get_draft_picks(draft_id)]

    def _resolve_slot(self, me: str, draft_data: dict) -> int | None:
        draft_order = draft_data.get("draft_order") or {}  # user_id -> slot
        if not draft_order:
            return None
        user_id = me if me.isdigit() else (self.get_user(me).get("user_id") or "")
        slot = draft_order.get(user_id)
        try:
            return int(slot) if slot is not None else None
        except (TypeError, ValueError):
            return None


def _roster_from_slots(settings: dict) -> list[str]:
    roster: list[str] = []
    for key, code in _SLOT_KEYS:
        count = settings.get(key)
        if count:
            roster.extend([code] * int(count))
    return roster


def _scoring_from_type(scoring_type: str | None) -> dict[str, float]:
    scoring = dict(DEFAULT_SCORING)
    rec = _PPR_BY_TYPE.get((scoring_type or "").lower())
    if rec is not None:
        scoring["rec"] = rec
    return scoring


def _league_from_payloads(league_data: dict, draft_data: dict) -> LeagueSettings:
    draft_settings = draft_data.get("settings") or {}
    meta = draft_data.get("metadata") or {}

    raw_roster = league_data.get("roster_positions")
    if isinstance(raw_roster, list) and raw_roster and isinstance(raw_roster[0], str):
        roster_positions = list(raw_roster)
    else:
        roster_positions = _roster_from_slots(draft_settings) or None

    num_teams = league_data.get("total_rosters") or draft_settings.get("teams") or 12

    scoring = league_data.get("scoring_settings")
    if scoring:
        scoring = {k: float(v) for k, v in scoring.items()}
    else:
        scoring = _scoring_from_type(meta.get("scoring_type"))

    kwargs: dict = {
        "name": league_data.get("name") or meta.get("name") or "Sleeper Mock Draft",
        "num_teams": int(num_teams),
        "scoring_settings": scoring,
    }
    if roster_positions:
        kwargs["roster_positions"] = roster_positions
    return LeagueSettings(**kwargs)


def _draft_slot_to_team(draft_data: dict, users: list[dict]) -> dict[int, str]:
    user_names = {u.get("user_id"): (u.get("display_name") or u.get("username") or "?") for u in users}
    draft_order = draft_data.get("draft_order") or {}  # user_id -> slot
    out: dict[int, str] = {}
    for user_id, slot in draft_order.items():
        try:
            out[int(slot)] = user_names.get(user_id, "?")
        except (TypeError, ValueError):
            continue
    return out


def _normalize_pick(pick: dict) -> dict:
    meta = pick.get("metadata") or {}
    first = (meta.get("first_name") or "").strip()
    last = (meta.get("last_name") or "").strip()
    name = (first + " " + last).strip() or meta.get("player_name") or pick.get("player_id", "")
    position = normalize_position(meta.get("position") or "")
    return {
        "pick_no": pick.get("pick_no"),
        "slot": pick.get("draft_slot"),
        "round": pick.get("round"),
        "player": name,
        "position": position,
        "team": (meta.get("team") or "").upper() or None,
        "player_id": pick.get("player_id"),
    }


def _place_pick(state: DraftState, p: dict) -> bool:
    """Set one normalized pick on the board. Returns True if it changed anything."""
    pick_no = p.get("pick_no")
    player = p.get("player")
    if not player or not pick_no:
        return False
    try:
        existing = state.get_pick(int(pick_no))
    except (IndexError, ValueError):
        return False
    if existing.player and existing.player.lower() == player.lower():
        return False
    if existing.is_made:
        state.clear_pick(int(pick_no))
    try:
        state.set_pick(
            int(pick_no),
            player=player,
            position=p.get("position") or "",
            team=p.get("team"),
            player_id=p.get("player_id"),
        )
    except (ValueError, IndexError):
        return False
    return True


def apply_import(state: DraftState, imported: SleeperImport, my_slot: int | None = None) -> DraftState:
    """Reconfigure ``state`` from an import and replay its picks."""
    state.reconfigure(imported.league, my_slot=my_slot if my_slot is not None else imported.my_slot)
    for p in imported.picks:
        _place_pick(state, p)
    return state


def apply_new_picks(state: DraftState, picks: list[dict]) -> int:
    """Add/replace picks on an already-configured board. Returns how many changed."""
    return sum(_place_pick(state, p) for p in picks)
