import pytest
from fastapi.testclient import TestClient

from fantasy_draft_tool.session import DraftSession
from fantasy_draft_tool.web import app as app_module


@pytest.fixture()
def client(tmp_path):
    fresh = DraftSession(session_file=tmp_path / "session.json")
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

    def fake_import(self, league_id=None, draft_id=None):
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
