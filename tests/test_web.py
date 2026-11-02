import pytest
from fastapi.testclient import TestClient

from fantasy_draft_tool.session import SAMPLE_PLAYERS, DraftSession
from fantasy_draft_tool.web import app as app_module


@pytest.fixture()
def client(tmp_path):
    # Pin to the sample pool so tests don't depend on data/player_pool.csv.
    fresh = DraftSession(projections_path=SAMPLE_PLAYERS, session_file=tmp_path / "session.json")
    app_module.session = fresh
    return TestClient(app_module.app)


def test_state_has_board_and_recommendations(client):
    body = client.get("/api/state").json()
    assert body["league"]["num_teams"] == 12
    assert len(body["draft"]["picks"]) == 12 * len(body["league"]["roster_positions"])
    assert body["recommendations"], "expected some recommendations from the sample pool"


def test_post_and_delete_pick(client):
    top = client.get("/api/players?q=&limit=1").json()[0]
    made = client.post("/api/picks/1", json={"player": top["player"], "position": top["position"]}).json()
    assert made["draft"]["picks"][0]["player"] == top["player"]
    assert made["draft"]["current_pick_no"] == 2

    cleared = client.delete("/api/picks/1").json()
    assert cleared["draft"]["picks"][0]["player"] is None
    assert cleared["draft"]["current_pick_no"] == 1


def test_duplicate_pick_is_a_400(client):
    top = client.get("/api/players?q=&limit=1").json()[0]
    client.post("/api/picks/1", json={"player": top["player"], "position": top["position"]})
    dup = client.post("/api/picks/2", json={"player": top["player"], "position": top["position"]})
    assert dup.status_code == 400


def test_put_league_reshapes_board(client):
    resp = client.put(
        "/api/league",
        json={
            "name": "Superflex Dynasty",
            "num_teams": 10,
            "roster_positions": ["QB", "RB", "WR", "TE", "SUPER_FLEX", "BN"],
            "scoring_settings": {"rec": 1.0},
            "my_slot": 4,
        },
    ).json()
    assert resp["league"]["name"] == "Superflex Dynasty"
    assert resp["draft"]["my_slot"] == 4
    assert len(resp["draft"]["picks"]) == 60


def test_players_search_filters_drafted(client):
    top = client.get("/api/players?q=&limit=1").json()[0]
    client.post("/api/picks/1", json={"player": top["player"], "position": top["position"]})
    names = [r["player"] for r in client.get("/api/players?q=&available=true&limit=50").json()]
    assert top["player"] not in names


def test_import_sleeper_uses_injected_client(client, monkeypatch):
    from fantasy_draft_tool import sleeper

    def fake_import(self, league_id=None, draft_id=None, me=None):
        return sleeper.SleeperImport(
            league=sleeper.LeagueSettings(name="Imported", num_teams=8),
            draft_id="d1",
            picks=[{"pick_no": 1, "slot": 1, "player": "Some Guy", "position": "RB", "team": "SF", "player_id": "x"}],
            draft_slot_to_team={1: "Me"},
        )

    monkeypatch.setattr(sleeper.SleeperClient, "import_league", fake_import)
    resp = client.post("/api/import/sleeper", json={"league_id": "999"}).json()
    assert resp["league"]["name"] == "Imported"
    assert resp["draft"]["picks"][0]["player"] == "Some Guy"


def test_sync_sleeper_pulls_new_picks_without_rebuild(client, monkeypatch):
    from fantasy_draft_tool import sleeper

    def fake_import(self, league_id=None, draft_id=None, me=None):
        return sleeper.SleeperImport(
            league=sleeper.LeagueSettings(name="Mock", num_teams=10),
            draft_id="mock1", is_mock=True, status="drafting",
            picks=[{"pick_no": 1, "player": "Player One", "position": "RB", "team": "SF", "player_id": "1"}],
            draft_slot_to_team={},
        )

    picks_calls = []

    def fake_sync_picks(self, draft_id):
        picks_calls.append(draft_id)
        return [
            {"pick_no": 1, "player": "Player One", "position": "RB", "team": "SF", "player_id": "1"},
            {"pick_no": 2, "player": "Player Two", "position": "WR", "team": "KC", "player_id": "2"},
        ]

    monkeypatch.setattr(sleeper.SleeperClient, "import_league", fake_import)
    monkeypatch.setattr(sleeper.SleeperClient, "sync_picks", fake_sync_picks)

    imported = client.post("/api/import/sleeper", json={"draft_id": "mock1"}).json()
    assert imported["draft"]["sleeper"]["is_mock"] is True
    assert imported["draft"]["picks"][1]["player"] is None

    synced = client.post("/api/sync/sleeper").json()
    assert picks_calls == ["mock1"]
    assert synced["draft"]["picks"][1]["player"] == "Player Two"
    assert synced["league"]["num_teams"] == 10


def test_sync_sleeper_without_link_is_400(client):
    assert client.post("/api/sync/sleeper").status_code == 400


def _rec_names(body):
    return [r["player"] for r in body["recommendations"]]


def test_reject_recommendation_backfills_list(client):
    before = client.get("/api/state").json()
    names = _rec_names(before)
    top = names[0]

    after = client.post("/api/recommendations/reject", json={"player": top}).json()
    after_names = _rec_names(after)
    assert top not in after_names
    assert len(after_names) == len(names)  # next-best player backfilled
    assert after_names[: len(names) - 1] == names[1:]
    assert after["rejected"] == [top.lower()]


def test_rejected_player_stays_draftable(client):
    top = _rec_names(client.get("/api/state").json())[0]
    body = client.post("/api/recommendations/reject", json={"player": top}).json()
    assert top in [p["player"] for p in body["best_available"]]
    assert top in [p["player"] for p in client.get(f"/api/players?q={top}").json()]

    made = client.post("/api/picks/1", json={"player": top}).json()
    assert made["draft"]["picks"][0]["player"] == top


def test_rejections_reset_when_pick_changes(client):
    names = _rec_names(client.get("/api/state").json())
    client.post("/api/recommendations/reject", json={"player": names[0]})

    # Someone else's pick advances the board: the rejection no longer applies.
    advanced = client.post("/api/picks/1", json={"player": names[3]}).json()
    assert advanced["rejected"] == []
    assert names[0] in _rec_names(advanced)

    # Undoing back to pick 1 doesn't bring the old rejection back.
    undone = client.delete("/api/picks/1").json()
    assert undone["rejected"] == []
    assert names[0] in _rec_names(undone)


def test_rejections_survive_reload_within_same_pick(client, tmp_path):
    top = _rec_names(client.get("/api/state").json())[0]
    client.post("/api/recommendations/reject", json={"player": top})

    reloaded = DraftSession(projections_path=SAMPLE_PLAYERS, session_file=tmp_path / "session.json")
    assert reloaded.load()
    state = reloaded.to_dict()
    assert state["rejected"] == [top.lower()]
    assert top not in _rec_names(state)


def test_clear_rejections_restores_list(client):
    names = _rec_names(client.get("/api/state").json())
    client.post("/api/recommendations/reject", json={"player": names[0]})
    cleared = client.delete("/api/recommendations/rejections").json()
    assert cleared["rejected"] == []
    assert _rec_names(cleared) == names


def test_static_assets_are_revalidated(client):
    # Browsers must re-check app.js/styles.css so UI updates show up without
    # a hard refresh.
    for path in ("/", "/app.js", "/styles.css"):
        assert client.get(path).headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/state").headers
