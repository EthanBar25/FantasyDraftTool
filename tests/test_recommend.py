from dataclasses import replace
from pathlib import Path

from fantasy_draft_tool.draft import DraftState
from fantasy_draft_tool.league import LeagueSettings
from fantasy_draft_tool.rankings import rank_from_csv
from fantasy_draft_tool.recommend import _roster_need, available_players, recommend

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


def test_streamer_positions_wait_until_late():
    league = LeagueSettings(num_teams=12)
    assert _roster_need("K", {}, league, late_draft=False)[0] < 0.5
    assert _roster_need("K", {}, league, late_draft=True)[0] > 1.0
    # Once you already have one, it drops to near-zero weight.
    assert _roster_need("DEF", {"DEF": 1}, league, late_draft=True)[0] < 0.2


def test_kicker_not_recommended_early_even_with_high_vor():
    state, pool = build()
    pool = list(pool) + [replace(pool[0], player="Boom Kicker", position="K", vor=60.0, adp=130.0)]
    recs = recommend(state, pool, limit=6)
    assert "Boom Kicker" not in [r.player for r in recs]


def test_adp_value_reason_and_bump():
    state, pool = build(my_slot=1, teams=4)  # pick 1 is on the clock
    faller = pool[5]
    pool = list(pool)
    pool[5] = replace(faller, adp=40.0)  # market says ~pick 40, available at 1

    recs = {r.player: r for r in recommend(state, pool, limit=50)}
    rec = recs[faller.player]
    assert rec.adp == 40.0
    assert any("value" in reason.lower() for reason in rec.reasons)
    assert rec.adjusted > rec.vor  # value multiplier applied
