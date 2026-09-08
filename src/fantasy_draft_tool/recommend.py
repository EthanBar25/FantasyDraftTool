"""Turn draft state + player projections into pick recommendations.

The score for an available player at *your* pick is:

    adjusted = vor * roster_need * positional_run * adp_value

where ``vor`` is value over replacement for your league, ``roster_need`` pushes
positions you still have to fill up the board (and parks kickers/defenses until
the final rounds), ``positional_run`` reacts to other teams hammering a position
since your last pick, and ``adp_value`` rewards players the market drafts earlier
than your current pick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median

from .draft import DraftState
from .league import FLEX_ELIGIBILITY, LeagueSettings
from .rankings import RankedPlayer

FLEX_POSITIONS = ("RB", "WR", "TE")
STREAM_POSITIONS = ("K", "DEF")  # last-round picks; don't chase them early


@dataclass
class Recommendation:
    player: str
    position: str
    team: str
    projected_points: float
    vor: float
    adjusted: float
    adp: float | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "player": self.player,
            "position": self.position,
            "team": self.team,
            "projected_points": round(self.projected_points, 1),
            "vor": round(self.vor, 1),
            "adjusted": round(self.adjusted, 1),
            "adp": round(self.adp, 1) if self.adp is not None else None,
            "reasons": self.reasons,
        }


def _flex_slot_total(league: LeagueSettings) -> int:
    return sum(
        count
        for flex_type, count in league.flex_slots.items()
        if set(FLEX_ELIGIBILITY[flex_type]) & set(FLEX_POSITIONS)
    )


def _roster_need(
    position: str,
    my_counts: dict[str, int],
    league: LeagueSettings,
    late_draft: bool,
) -> tuple[float, str | None]:
    required = league.dedicated_starters
    have = my_counts.get(position, 0)

    if position in STREAM_POSITIONS:
        if have >= max(required.get(position, 0), 1):
            return 0.05, f"already have a {position}"
        if late_draft:
            return 1.2, f"need a {position} — draft's almost done"
        return 0.1, f"{position} can wait for the last rounds"

    starters_left = max(required.get(position, 0) - have, 0)

    if starters_left > 0:
        label = f"{position}{have + 1} need"
        if have == 0:
            label = f"no starting {position} yet"
        return 1.3 + 0.2 * (starters_left - 1), label

    if position in FLEX_POSITIONS:
        flex_total = _flex_slot_total(league)
        surplus = sum(
            max(my_counts.get(p, 0) - required.get(p, 0), 0) for p in FLEX_POSITIONS
        )
        if flex_total - surplus > 0:
            return 1.1, "fills your FLEX"

    if have < required.get(position, 0) + 2:
        return 0.9, None
    return 0.5, "already deep here"


def _positional_run(position: str, state: DraftState) -> tuple[float, str | None]:
    current = state.current_pick_no
    if current is None:
        return 1.0, None
    window_start = max(current - state.league.num_teams, 1)
    recent = [
        p
        for p in state.picks
        if window_start <= p.pick_no < current and p.position == position
    ]
    if len(recent) >= 4:
        return 1.0 + 0.06 * len(recent), f"{len(recent)} {position}s gone since your last pick"
    return 1.0, None


def _adp_value(adp: float | None, current_pick_no: int | None) -> tuple[float, str | None]:
    """Reward taking a player the market drafts earlier than here; flag reaches."""
    if adp is None or current_pick_no is None:
        return 1.0, None
    delta = adp - current_pick_no  # positive => still here past his ADP
    if delta >= 10:
        return 1.12, f"value — ADP {adp:.0f}, still on the board at {current_pick_no}"
    if delta >= 4:
        return 1.05, f"slight value vs ADP {adp:.0f}"
    if delta <= -18:
        return 0.9, f"reach — ADP {adp:.0f}, ~{-delta:.0f} picks early"
    return 1.0, None


def _tier_cliff(
    position: str, value: float, same_pos_values: list[float]
) -> str | None:
    """Flag when the next player at this position is a big step down."""
    below = [v for v in same_pos_values if v < value]
    if not below:
        return None
    gap = value - below[0]
    gaps = [a - b for a, b in pairwise(same_pos_values)]
    typical = median(gaps) if gaps else 0.0
    if gap >= max(2 * typical, 8.0):
        return f"last of the tier (next {position} is {gap:.0f} pts worse)"
    return None


def available_players(state: DraftState, pool: list[RankedPlayer]) -> list[RankedPlayer]:
    drafted = state.drafted_names()
    return [p for p in pool if p.player.lower() not in drafted]


def recommend(
    state: DraftState,
    pool: list[RankedPlayer],
    limit: int = 8,
) -> list[Recommendation]:
    league = state.league
    avail = sorted(available_players(state, pool), key=lambda p: p.vor, reverse=True)
    my_counts: dict[str, int] = {}
    for pick in state.my_roster():
        if pick.position:
            my_counts[pick.position] = my_counts.get(pick.position, 0) + 1

    current = state.current_pick_no
    total_rounds = len(league.roster_positions)
    current_round = state.get_pick(current).round if current else total_rounds
    late_draft = current_round >= total_rounds - 1

    by_pos: dict[str, list[float]] = {}
    for p in avail:
        by_pos.setdefault(p.position, []).append(p.vor)

    scored: list[Recommendation] = []
    for p in avail:
        need_mult, need_reason = _roster_need(p.position, my_counts, league, late_draft)
        run_mult, run_reason = _positional_run(p.position, state)
        if p.position in STREAM_POSITIONS:
            adp_mult, adp_reason = 1.0, None
        else:
            adp_mult, adp_reason = _adp_value(p.adp, current)
        adjusted = p.vor * need_mult * run_mult * adp_mult

        reasons: list[str] = []
        if need_reason:
            reasons.append(need_reason)
        if run_reason:
            reasons.append(run_reason)
        if adp_reason:
            reasons.append(adp_reason)
        cliff = _tier_cliff(p.position, p.vor, by_pos.get(p.position, []))
        if cliff:
            reasons.append(cliff)
            adjusted *= 1.1
        if p is avail[0]:
            reasons.append(f"best value on the board (+{p.vor:.0f} VOR)")

        scored.append(
            Recommendation(
                player=p.player,
                position=p.position,
                team=p.team,
                projected_points=p.projected_points,
                vor=p.vor,
                adjusted=adjusted,
                adp=p.adp,
                reasons=reasons,
            )
        )

    scored.sort(key=lambda r: r.adjusted, reverse=True)
    return scored[:limit]
