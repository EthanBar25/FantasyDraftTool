from fantasy_draft_tool.league import LeagueSettings


def test_rounds_equal_roster_slots():
    league = LeagueSettings(roster_positions=["QB", "RB", "WR", "BN", "BN"])
    assert league.rounds == 5


def test_dedicated_starters_exclude_flex_and_bench():
    league = LeagueSettings(
        roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN"]
    )
    assert league.dedicated_starters["RB"] == 2
    assert league.dedicated_starters["WR"] == 2
    assert "FLEX" not in league.dedicated_starters
    assert sum(league.flex_slots.values()) == 1


def test_replacement_ranks_scale_with_teams_and_flex():
    league = LeagueSettings(
        num_teams=10,
        roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
    )
    ranks = league.replacement_ranks()
    # 2 RB starters * 10 teams = 20, plus a third of the 10 flex slots, plus buffer.
    assert ranks["RB"] > 20
    assert ranks["QB"] >= 10
    # WR shares the flex too, so it lands above its 20 dedicated starters.
    assert ranks["WR"] > 20


def test_superflex_detected_and_boosts_qb_replacement():
    base = LeagueSettings(roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"])
    sf = LeagueSettings(roster_positions=["QB", "RB", "WR", "TE", "SUPER_FLEX", "BN"])
    assert sf.is_superflex() and not base.is_superflex()
    assert sf.replacement_ranks()["QB"] > base.replacement_ranks()["QB"]


def test_roundtrip_dict():
    league = LeagueSettings(name="Dynasty", num_teams=14)
    assert LeagueSettings.from_dict(league.to_dict()).to_dict() == league.to_dict()


def test_position_aliases_normalized():
    league = LeagueSettings(roster_positions=["QB", "RB", "WR", "TE", "PK", "DST"])
    assert "K" in league.roster_positions and "DEF" in league.roster_positions
