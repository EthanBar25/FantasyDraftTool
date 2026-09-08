from fantasy_draft_tool.draft import DraftState
from fantasy_draft_tool.league import LeagueSettings
from fantasy_draft_tool.sleeper import SleeperClient, apply_import

LEAGUE_ID = "111"
DRAFT_ID = "222"

FAKE = {
    f"https://api.sleeper.app/v1/league/{LEAGUE_ID}": {
        "name": "The Show",
        "total_rosters": 10,
        "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"],
        "scoring_settings": {"rec": 0.5, "pass_td": 4, "rush_td": 6},
    },
    f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/users": [
        {"user_id": "u1", "display_name": "Ethan"},
        {"user_id": "u2", "display_name": "Rival"},
    ],
    f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/drafts": [{"draft_id": DRAFT_ID}],
    f"https://api.sleeper.app/v1/draft/{DRAFT_ID}": {
        "draft_id": DRAFT_ID,
        "league_id": LEAGUE_ID,
        "settings": {"teams": 10, "rounds": 11},
        "draft_order": {"u1": 3, "u2": 4},
    },
    f"https://api.sleeper.app/v1/draft/{DRAFT_ID}/picks": [
        {
            "pick_no": 1, "round": 1, "draft_slot": 1, "player_id": "4046",
            "metadata": {"first_name": "Christian", "last_name": "McCaffrey", "position": "RB", "team": "SF"},
        },
        {
            "pick_no": 2, "round": 1, "draft_slot": 2, "player_id": "6794",
            "metadata": {"first_name": "Ja'Marr", "last_name": "Chase", "position": "WR", "team": "CIN"},
        },
    ],
}


def fake_get_json(url):
    return FAKE[url]


def test_import_league_by_league_id_pulls_settings_and_picks():
    client = SleeperClient(get_json=fake_get_json)
    imported = client.import_league(league_id=LEAGUE_ID)

    assert isinstance(imported.league, LeagueSettings)
    assert imported.league.name == "The Show"
    assert imported.league.num_teams == 10
    assert imported.league.scoring_settings["rec"] == 0.5
    assert imported.draft_id == DRAFT_ID
    assert imported.draft_slot_to_team == {3: "Ethan", 4: "Rival"}
    assert [p["player"] for p in imported.picks] == ["Christian McCaffrey", "Ja'Marr Chase"]
    assert imported.picks[0]["position"] == "RB"


def test_import_by_draft_id_only_resolves_league():
    client = SleeperClient(get_json=fake_get_json)
    imported = client.import_league(draft_id=DRAFT_ID)
    assert imported.league.name == "The Show"


def test_apply_import_replays_picks_onto_state():
    client = SleeperClient(get_json=fake_get_json)
    imported = client.import_league(league_id=LEAGUE_ID)

    state = DraftState(LeagueSettings(), my_slot=1)
    apply_import(state, imported, my_slot=3)

    assert state.league.num_teams == 10
    assert state.my_slot == 3
    assert state.get_pick(1).player == "Christian McCaffrey"
    assert state.get_pick(2).player == "Ja'Marr Chase"
    assert state.current_pick_no == 3


def test_import_requires_an_id():
    client = SleeperClient(get_json=fake_get_json)
    try:
        client.import_league()
    except ValueError as exc:
        assert "league_id or a draft_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
