from pathlib import Path

from fantasy_draft_tool.draft import DraftState
from fantasy_draft_tool.league import LeagueSettings
from fantasy_draft_tool.rankings import rank_from_csv
from fantasy_draft_tool.recommend import available_players, recommend

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_players.csv"


def build(my_slot=1, teams=4):
    league = LeagueSettings(
        num_teams=teams,
        roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
    )
    pool = rank_from_csv(SAMPLE, league.replacement_ranks())
    state = DraftState(league, my_slot=my_slot)
    return state, pool


def test_available_shrinks_after_a_pick():
    state, pool = build()
    before = len(available_players(state, pool))
    state.set_pick(1, pool[0].player, pool[0].position, pool[0].team)
    assert len(available_players(state, pool)) == before - 1


def test_recommend_is_limited_and_sorted():
    state, pool = build()
    recs = recommend(state, pool, limit=5)
    assert len(recs) == 5
    assert [r.adjusted for r in recs] == sorted((r.adjusted for r in recs), reverse=True)


def test_filling_a_position_lowers_its_recommendation_weight():
    state, pool = build(my_slot=1, teams=4)
    rbs = [p for p in pool if p.position == "RB"]
    target = rbs[3]  # a mid RB still available later

    before = {r.player: r.adjusted for r in recommend(state, pool, limit=50)}

    # My slot-1 picks in a 4-team draft are overall 1 and 8; fill both with RBs.
    state.set_pick(1, rbs[0].player, "RB", rbs[0].team)
    state.set_pick(8, rbs[1].player, "RB", rbs[1].team)
    after = {r.player: r.adjusted for r in recommend(state, pool, limit=50)}

    assert after[target.player] < before[target.player]


def test_roster_need_reason_surfaces_for_empty_roster():
    state, pool = build()
    recs = recommend(state, pool, limit=10)
    joined = " ".join(r for rec in recs for r in rec.reasons)
    assert "need" in joined or "no starting" in joined
