"""League configuration, modeled on Sleeper's league settings.

Sleeper describes a league with:
  * ``roster_positions`` — an ordered list of slots, e.g.
    ``["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"]``
  * ``scoring_settings`` — a flat ``{stat: points}`` map (e.g. ``{"rec": 0.5}``)
  * ``total_rosters`` — number of teams

We keep those fields close to Sleeper's shape so importing a real league is a
near-direct copy (see :mod:`fantasy_draft_tool.sleeper`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# Slots that don't hold a real player.
BENCH_SLOTS = {"BN", "IR", "TAXI"}

# Which real positions each flex-style slot can be filled by.
FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    "IDP_FLEX": ("DL", "LB", "DB"),
}

# Sleeper writes defense as "DEF"; projection sources often use "DST".
POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}

STANDARD_ROSTER = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN", "BN", "BN"]

# A reasonable half-PPR default; overwritten by an imported league.
DEFAULT_SCORING = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 0.5,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fum_lost": -2.0,
}


def normalize_position(position: str) -> str:
    p = position.strip().upper()
    return POSITION_ALIASES.get(p, p)


@dataclass
class LeagueSettings:
    name: str = "My League"
    num_teams: int = 12
    roster_positions: list[str] = field(default_factory=lambda: list(STANDARD_ROSTER))
    scoring_settings: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SCORING))

    def __post_init__(self) -> None:
        self.roster_positions = [normalize_position(s) for s in self.roster_positions]

    # -- derived roster shape -------------------------------------------------

    @property
    def rounds(self) -> int:
        """One draft round per roster slot, bench included."""
        return len(self.roster_positions)

    @property
    def starter_slots(self) -> list[str]:
        return [s for s in self.roster_positions if s not in BENCH_SLOTS]

    @property
    def dedicated_starters(self) -> Counter[str]:
        """Starting slots locked to a single position (excludes flex slots)."""
        return Counter(s for s in self.starter_slots if s not in FLEX_ELIGIBILITY)

    @property
    def flex_slots(self) -> Counter[str]:
        """Flex-style starting slots, by flex type."""
        return Counter(s for s in self.starter_slots if s in FLEX_ELIGIBILITY)

    def is_superflex(self) -> bool:
        return "SUPER_FLEX" in self.flex_slots

    def replacement_ranks(self) -> dict[str, int]:
        """Rank of the "replacement level" player at each position.

        A player is only worth their points *above* what you could get for free
        later. We approximate replacement level as the last starter drafted
        across the league at that position: dedicated starting slots, plus each
        position's share of the flex slots it is eligible for.
        """
        ranks: dict[str, float] = {
            pos: count * self.num_teams for pos, count in self.dedicated_starters.items()
        }
        for flex_type, count in self.flex_slots.items():
            eligible = FLEX_ELIGIBILITY[flex_type]
            share = (count * self.num_teams) / len(eligible)
            for pos in eligible:
                ranks[pos] = ranks.get(pos, 0.0) + share
        # A small buffer past the last starter, and never below one full round.
        return {
            pos: max(round(value) + self.num_teams // 2, self.num_teams)
            for pos, value in ranks.items()
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "num_teams": self.num_teams,
            "roster_positions": list(self.roster_positions),
            "scoring_settings": dict(self.scoring_settings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> LeagueSettings:
        return cls(
            name=data.get("name", "My League"),
            num_teams=int(data.get("num_teams", 12)),
            roster_positions=list(data.get("roster_positions") or STANDARD_ROSTER),
            scoring_settings=dict(data.get("scoring_settings") or DEFAULT_SCORING),
        )
