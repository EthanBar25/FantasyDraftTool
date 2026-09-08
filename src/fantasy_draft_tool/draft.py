"""Draft state: snake pick order, the picks made so far, and per-team rosters."""

from __future__ import annotations

from dataclasses import dataclass

from .league import LeagueSettings, normalize_position


@dataclass
class Pick:
    pick_no: int          # 1-based, overall
    round: int            # 1-based
    slot: int             # 1-based draft slot (seat at the table)
    player: str | None = None
    position: str | None = None
    team: str | None = None
    player_id: str | None = None  # e.g. Sleeper id, when imported

    @property
    def is_made(self) -> bool:
        return self.player is not None

    def to_dict(self) -> dict:
        return {
            "pick_no": self.pick_no,
            "round": self.round,
            "slot": self.slot,
            "player": self.player,
            "position": self.position,
            "team": self.team,
            "player_id": self.player_id,
        }


def slot_for_pick(pick_no: int, num_teams: int) -> tuple[int, int]:
    """Return ``(round, slot)`` for an overall pick number in a snake draft."""
    if pick_no < 1:
        raise ValueError("pick_no is 1-based")
    rnd = (pick_no - 1) // num_teams + 1
    index_in_round = (pick_no - 1) % num_teams  # 0-based
    if rnd % 2 == 1:
        slot = index_in_round + 1
    else:
        slot = num_teams - index_in_round
    return rnd, slot


class DraftState:
    def __init__(self, league: LeagueSettings, my_slot: int = 1) -> None:
        self.league = league
        self.my_slot = my_slot
        self.picks: list[Pick] = []
        self._rebuild_board()

    # -- board construction -------------------------------------------------

    def _rebuild_board(self) -> None:
        num_teams = self.league.num_teams
        total = num_teams * self.league.rounds
        made = {p.pick_no: p for p in self.picks if p.is_made}
        self.picks = []
        for pick_no in range(1, total + 1):
            rnd, slot = slot_for_pick(pick_no, num_teams)
            prior = made.get(pick_no)
            if prior is not None:
                prior.round, prior.slot = rnd, slot
                self.picks.append(prior)
            else:
                self.picks.append(Pick(pick_no=pick_no, round=rnd, slot=slot))

    def reconfigure(self, league: LeagueSettings, my_slot: int | None = None) -> None:
        self.league = league
        if my_slot is not None:
            self.my_slot = my_slot
        self.my_slot = min(self.my_slot, league.num_teams)
        self._rebuild_board()

    # -- pick mutation ----------------------------------------------------

    def get_pick(self, pick_no: int) -> Pick:
        return self.picks[pick_no - 1]

    def set_pick(
        self,
        pick_no: int,
        player: str,
        position: str,
        team: str | None = None,
        player_id: str | None = None,
    ) -> Pick:
        if self.is_drafted(player):
            raise ValueError(f"{player} is already drafted")
        pick = self.get_pick(pick_no)
        pick.player = player
        pick.position = normalize_position(position)
        pick.team = team
        pick.player_id = player_id
        return pick

    def clear_pick(self, pick_no: int) -> None:
        pick = self.get_pick(pick_no)
        pick.player = pick.position = pick.team = pick.player_id = None

    def reset(self) -> None:
        for pick in self.picks:
            pick.player = pick.position = pick.team = pick.player_id = None

    # -- queries --------------------------------------------------------

    @property
    def current_pick_no(self) -> int | None:
        for pick in self.picks:
            if not pick.is_made:
                return pick.pick_no
        return None

    def drafted_names(self) -> set[str]:
        return {p.player.lower() for p in self.picks if p.player}

    def is_drafted(self, player: str) -> bool:
        return player.lower() in self.drafted_names()

    def roster_for_slot(self, slot: int) -> list[Pick]:
        return [p for p in self.picks if p.slot == slot and p.is_made]

    def my_roster(self) -> list[Pick]:
        return self.roster_for_slot(self.my_slot)

    def upcoming_picks_for_slot(self, slot: int, limit: int = 5) -> list[int]:
        out = [p.pick_no for p in self.picks if p.slot == slot and not p.is_made]
        return out[:limit]

    def my_upcoming_picks(self, limit: int = 5) -> list[int]:
        return self.upcoming_picks_for_slot(self.my_slot, limit)

    def picks_between_now_and_my_next(self) -> int:
        nxt = self.my_upcoming_picks(1)
        cur = self.current_pick_no
        if not nxt or cur is None:
            return 0
        return nxt[0] - cur

    def to_dict(self) -> dict:
        return {
            "my_slot": self.my_slot,
            "current_pick_no": self.current_pick_no,
            "league": self.league.to_dict(),
            "picks": [p.to_dict() for p in self.picks],
        }
