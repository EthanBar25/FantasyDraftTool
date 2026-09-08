import pytest

from fantasy_draft_tool.draft import DraftState, slot_for_pick
from fantasy_draft_tool.league import LeagueSettings


def test_snake_order():
    assert slot_for_pick(1, 12) == (1, 1)
    assert slot_for_pick(12, 12) == (1, 12)
    assert slot_for_pick(13, 12) == (2, 12)  # snake back
    assert slot_for_pick(24, 12) == (2, 1)
    assert slot_for_pick(25, 12) == (3, 1)


def make_state(rounds=3, teams=4, my_slot=2):
    league = LeagueSettings(num_teams=teams, roster_positions=["QB", "RB", "WR"][:rounds])
    return DraftState(league, my_slot=my_slot)


def test_board_size_and_first_open_pick():
    state = make_state()
    assert len(state.picks) == 12
    assert state.current_pick_no == 1


def test_set_and_clear_pick_advances_clock():
    state = make_state()
    state.set_pick(1, "Player A", "RB", "SF")
    assert state.current_pick_no == 2
    assert state.get_pick(1).round == 1 and state.get_pick(1).slot == 1
    state.clear_pick(1)
    assert state.current_pick_no == 1


def test_duplicate_player_rejected():
    state = make_state()
    state.set_pick(1, "Player A", "RB")
    with pytest.raises(ValueError, match="already drafted"):
        state.set_pick(2, "player a", "RB")


def test_my_upcoming_picks_follow_snake():
    state = make_state(rounds=3, teams=4, my_slot=2)
    # slot 2 picks: overall 2, then 7 (round 2 reversed), then 10 (round 3)
    assert state.my_upcoming_picks() == [2, 7, 10]
    state.set_pick(1, "A", "RB")
    # Pick 2 is now on the clock and it's my seat, so my next pick is 0 away.
    assert state.picks_between_now_and_my_next() == 0
    state.set_pick(2, "B", "RB")
    # Now pick 3 is up; my next turn is overall pick 7.
    assert state.my_upcoming_picks()[0] == 7
    assert state.picks_between_now_and_my_next() == 4


def test_reconfigure_preserves_made_picks_and_remaps_slots():
    state = make_state(rounds=3, teams=4)
    state.set_pick(5, "Kept Player", "WR", "KC")
    bigger = LeagueSettings(num_teams=6, roster_positions=["QB", "RB", "WR", "TE"])
    state.reconfigure(bigger)
    kept = state.get_pick(5)
    assert kept.player == "Kept Player"
    assert kept.slot == 5 and kept.round == 1  # pick 5 in a 6-team league
    assert len(state.picks) == 24
