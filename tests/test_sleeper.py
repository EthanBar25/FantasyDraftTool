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


# -- mock drafts (a draft with no league) --------------------------------

MOCK_ID = "999"

MOCK_FAKE = {
    f"https://api.sleeper.app/v1/draft/{MOCK_ID}": {
        "draft_id": MOCK_ID,
        "league_id": None,
        "status": "drafting",
        "type": "snake",
        "settings": {
            "teams": 10,
            "rounds": 15,
            "slots_qb": 1,
            "slots_rb": 2,
            "slots_wr": 3,
            "slots_te": 1,
            "slots_flex": 1,
            "slots_super_flex": 1,
            "slots_k": 1,
            "slots_def": 1,
            "slots_bn": 4,
        },
        "metadata": {"scoring_type": "half_ppr", "name": "Sunday Mock"},
        "draft_order": {"u_ethan": 7},
    },
    f"https://api.sleeper.app/v1/draft/{MOCK_ID}/picks": [
        {"pick_no": 1, "round": 1, "draft_slot": 1, "player_id": "4046",
         "metadata": {"first_name": "Josh", "last_name": "Allen", "position": "QB", "team": "BUF"}},
    ],
    "https://api.sleeper.app/v1/user/EthanBar": {"user_id": "u_ethan", "username": "ethanbar"},
}


def mock_get_json(url):
    return MOCK_FAKE[url]


def test_mock_draft_rebuilds_roster_and_scoring_from_draft():
    imported = SleeperClient(get_json=mock_get_json).import_league(draft_id=MOCK_ID)

    assert imported.is_mock is True
    assert imported.status == "drafting"
    assert imported.league.name == "Sunday Mock"
    assert imported.league.num_teams == 10
    assert imported.league.scoring_settings["rec"] == 0.5  # half_ppr
    # 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 1 SUPER_FLEX, 1 K, 1 DEF, 4 BN = 15
    rp = imported.league.roster_positions
    assert rp.count("RB") == 2 and rp.count("WR") == 3
    assert "SUPER_FLEX" in rp and rp.count("BN") == 4
    assert len(rp) == 15


def test_mock_draft_resolves_my_slot_from_username():
    imported = SleeperClient(get_json=mock_get_json).import_league(draft_id=MOCK_ID, me="EthanBar")
    assert imported.my_slot == 7


def test_apply_new_picks_adds_without_reconfiguring():
    from fantasy_draft_tool.sleeper import apply_new_picks

    client = SleeperClient(get_json=mock_get_json)
    imported = client.import_league(draft_id=MOCK_ID)
    state = DraftState(LeagueSettings(), my_slot=1)
    apply_import(state, imported)
    assert state.get_pick(1).player == "Josh Allen"

    later = [
        {"pick_no": 1, "player": "Josh Allen", "position": "QB", "team": "BUF", "player_id": "4046"},
        {"pick_no": 2, "player": "Bijan Robinson", "position": "RB", "team": "ATL", "player_id": "x"},
    ]
    changed = apply_new_picks(state, later)
    assert changed == 1  # pick 1 unchanged, pick 2 is new
    assert state.get_pick(2).player == "Bijan Robinson"
    assert state.league.num_teams == 10  # board not rebuilt
