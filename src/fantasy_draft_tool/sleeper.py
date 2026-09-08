"""Read-only client for Sleeper's public API.

Docs: https://docs.sleeper.com/ — no auth needed for reads.

Used to import a league's rules (scoring, roster slots, team count) and, if a
draft has started, the picks already made.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from .draft import DraftState
from .league import LeagueSettings, normalize_position

API_BASE = "https://api.sleeper.app/v1"

GetJson = Callable[[str], Any]


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

    # -- high level ---------------------------------------------------

    def import_league(
        self, league_id: str | None = None, draft_id: str | None = None
    ) -> SleeperImport:
        """Build a :class:`SleeperImport` from a league id, a draft id, or both."""
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
            if not league_id:
                league_id = draft_data.get("league_id")
                if league_id:
                    league_data = self.get_league(league_id) or {}
                    users = self.get_league_users(league_id)

        settings = _league_from_payloads(league_data, draft_data)

        slot_to_team = _draft_slot_to_team(draft_data, users)
        picks_raw = self.get_draft_picks(draft_id) if draft_id else []
        picks = [_normalize_pick(p) for p in picks_raw]

        return SleeperImport(
            league=settings,
            draft_id=draft_id,
            picks=picks,
            draft_slot_to_team=slot_to_team,
        )


def _league_from_payloads(league_data: dict, draft_data: dict) -> LeagueSettings:
    draft_settings = draft_data.get("settings") or {}
    raw_roster = league_data.get("roster_positions")
    roster_positions = (
        list(raw_roster) if isinstance(raw_roster, list) and raw_roster and isinstance(raw_roster[0], str) else None
    )

    num_teams = (
        league_data.get("total_rosters")
        or draft_settings.get("teams")
        or 12
    )
    scoring = league_data.get("scoring_settings") or {}

    kwargs: dict = {
        "name": league_data.get("name") or draft_data.get("metadata", {}).get("name") or "Imported League",
        "num_teams": int(num_teams),
        "scoring_settings": {k: float(v) for k, v in scoring.items()},
    }
    if roster_positions:
        kwargs["roster_positions"] = roster_positions
    settings = LeagueSettings(**kwargs)
    return settings


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


def apply_import(state: DraftState, imported: SleeperImport, my_slot: int | None = None) -> DraftState:
    """Reconfigure ``state`` from an import and replay its picks."""
    state.reconfigure(imported.league, my_slot=my_slot)
    for p in imported.picks:
        if not p.get("player") or not p.get("pick_no"):
            continue
        try:
            state.set_pick(
                int(p["pick_no"]),
                player=p["player"],
                position=p.get("position") or "",
                team=p.get("team"),
                player_id=p.get("player_id"),
            )
        except (ValueError, IndexError):
            continue
    return state
