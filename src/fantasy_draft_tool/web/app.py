"""FastAPI app that serves the draft board and its JSON API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..league import LeagueSettings
from ..session import DraftSession

STATIC_DIR = Path(__file__).parent / "static"

session = DraftSession()
session.load()

app = FastAPI(title="FantasyDraftTool")


# -- request bodies ---------------------------------------------------

class LeagueBody(BaseModel):
    name: str = "My League"
    num_teams: int = 12
    roster_positions: list[str]
    scoring_settings: dict[str, float] = {}
    my_slot: int | None = None


class MySlotBody(BaseModel):
    slot: int


class PickBody(BaseModel):
    player: str
    position: str = ""
    team: str | None = None
    player_id: str | None = None


class SleeperBody(BaseModel):
    league_id: str | None = None
    draft_id: str | None = None
    my_slot: int | None = None


# -- routes ---------------------------------------------------------

@app.get("/api/state")
def get_state() -> dict:
    return session.to_dict()


@app.put("/api/league")
def put_league(body: LeagueBody) -> dict:
    league = LeagueSettings(
        name=body.name,
        num_teams=body.num_teams,
        roster_positions=body.roster_positions,
        scoring_settings=body.scoring_settings or LeagueSettings().scoring_settings,
    )
    session.set_league(league, my_slot=body.my_slot)
    return session.to_dict()


@app.put("/api/my-slot")
def put_my_slot(body: MySlotBody) -> dict:
    session.set_my_slot(body.slot)
    return session.to_dict()


@app.get("/api/players")
def search_players(q: str = "", available: bool = True, limit: int = 12) -> list[dict]:
    return session.search_players(q, limit=limit, only_available=available)


@app.post("/api/picks/{pick_no}")
def post_pick(pick_no: int, body: PickBody) -> dict:
    try:
        session.set_pick(
            pick_no,
            player=body.player,
            position=body.position,
            team=body.team,
            player_id=body.player_id,
        )
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@app.delete("/api/picks/{pick_no}")
def delete_pick(pick_no: int) -> dict:
    try:
        session.clear_pick(pick_no)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="no such pick") from exc
    return session.to_dict()


@app.post("/api/reset")
def post_reset() -> dict:
    session.reset()
    return session.to_dict()


@app.post("/api/import/sleeper")
def post_import_sleeper(body: SleeperBody) -> dict:
    if not body.league_id and not body.draft_id:
        raise HTTPException(status_code=400, detail="provide league_id or draft_id")
    try:
        session.import_sleeper(body.league_id, body.draft_id, my_slot=body.my_slot)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sleeper import failed: {exc}") from exc
    return session.to_dict()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def run() -> None:
    import uvicorn

    uvicorn.run("fantasy_draft_tool.web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
