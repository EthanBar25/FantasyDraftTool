from pathlib import Path

import pytest

from fantasy_draft_tool.rankings import load_projections, rank_from_csv

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_players.csv"


def test_load_projections_reads_sample():
    df = load_projections(SAMPLE)
    assert {"player", "position", "team", "projected_points"} <= set(df.columns)
    assert len(df) == 30


def test_load_projections_rejects_missing_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("player,team\nSomeone,SF\n")
    with pytest.raises(ValueError, match="missing required column"):
        load_projections(bad)


def test_rank_from_csv_orders_by_vor():
    players = rank_from_csv(SAMPLE)
    assert players[0].overall_rank == 1
    # VOR must be non-increasing down the board.
    vors = [p.vor for p in players]
    assert vors == sorted(vors, reverse=True)


def test_position_ranks_are_dense_per_position():
    players = rank_from_csv(SAMPLE)
    rbs = sorted((p for p in players if p.position == "RB"), key=lambda p: p.position_rank)
    assert [p.position_rank for p in rbs] == list(range(1, len(rbs) + 1))
