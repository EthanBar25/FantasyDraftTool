import pandas as pd
import pytest

from fantasy_draft_tool.datasets import (
    _weighted_ppg,
    build_dataset,
    fetch_adp,
    fetch_player_status,
    fetch_seasonal_stats,
    load_adp_snapshot,
)

ADP_PAYLOAD = {
    "status": "Success",
    "players": [
        {"name": "James Cook III", "position": "RB", "team": "BUF", "adp": 9.5,
         "stdev": 3.1, "times_drafted": 120, "bye": 7},
        {"name": "Ja'Marr Chase", "position": "WR", "team": "CIN", "adp": 3.9,
         "stdev": 1.2, "times_drafted": 200, "bye": 10},
        {"name": "Chicago Defense", "position": "DEF", "team": "CHI", "adp": 130.0,
         "stdev": 8.0, "times_drafted": 30, "bye": 5},
    ],
}

STATUS_PAYLOAD = {
    "1": {
        "full_name": "James Cook", "position": "RB", "fantasy_positions": ["RB"], "team": "BUF",
        "status": "Active", "injury_status": "Questionable",
        "injury_notes": "knee", "injury_body_part": "Knee",
    },
    "2": {
        "full_name": "Ja'Marr Chase", "position": "WR", "fantasy_positions": ["WR"], "team": "CIN",
        "status": "Active", "injury_status": "", "injury_notes": "",
    },
}


def fake_get_status_json(url):
    assert "sleeper.app" in url
    return STATUS_PAYLOAD


def _stats_frame(year, rows):
    base = {
        "player_display_name": None, "position": None, "recent_team": None, "games": 0,
        "fantasy_points": 0.0, "fantasy_points_ppr": 0.0, "passing_yards": 0,
        "passing_tds": 0, "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
        "receptions": 0, "receiving_yards": 0, "receiving_tds": 0,
    }
    return pd.DataFrame([{**base, **r} for r in rows]).assign(season=year)


STATS = {
    2023: _stats_frame(2023, [
        {"player_display_name": "James Cook", "position": "RB", "recent_team": "BUF",
         "games": 16, "fantasy_points": 160.0, "fantasy_points_ppr": 220.0},
        {"player_display_name": "Ja'Marr Chase", "position": "WR", "recent_team": "CIN",
         "games": 16, "fantasy_points": 200.0, "fantasy_points_ppr": 280.0},
        {"player_display_name": "Practice Squad Guy", "position": "LB", "recent_team": "CHI",
         "games": 1, "fantasy_points": 0.0, "fantasy_points_ppr": 0.0},
    ]),
    2024: _stats_frame(2024, [
        {"player_display_name": "James Cook", "position": "RB", "recent_team": "BUF",
         "games": 17, "fantasy_points": 170.0, "fantasy_points_ppr": 230.0},
        {"player_display_name": "Ja'Marr Chase", "position": "WR", "recent_team": "CIN",
         "games": 17, "fantasy_points": 280.0, "fantasy_points_ppr": 400.0},
    ]),
    2025: _stats_frame(2025, [
        {"player_display_name": "James Cook", "position": "RB", "recent_team": "BUF",
         "games": 17, "fantasy_points": 200.0, "fantasy_points_ppr": 260.0},
    ]),
}


def fake_get_json(url):
    assert "adp" in url
    return ADP_PAYLOAD


def fake_read_csv(url):
    year = int(url.split("_")[-1].split(".")[0])
    return STATS[year].copy()


def test_fetch_adp_shapes_rows_and_key():
    df = fetch_adp(2026, get_json=fake_get_json)
    assert set(df["player"]) == {"James Cook III", "Ja'Marr Chase", "Chicago Defense"}
    cook = df[df["player"] == "James Cook III"].iloc[0]
    assert cook["adp"] == 9.5 and cook["position"] == "RB"
    assert cook["key"] == "james cook|RB"  # suffix + punctuation stripped


def test_fetch_seasonal_stats_normalizes_and_filters():
    df = fetch_seasonal_stats(2023, read_csv=fake_read_csv)
    assert "Practice Squad Guy" not in set(df["player"])  # LB filtered out
    row = df[df["player"] == "Ja'Marr Chase"].iloc[0]
    assert row["points_half"] == (200.0 + 280.0) / 2
    assert row["season"] == 2023


def test_build_dataset_merges_stats_with_adp():
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026, scoring="half-ppr",
        get_json=fake_get_json, read_csv=fake_read_csv, get_status_json=fake_get_status_json,
    )
    by_name = df.set_index("player")

    cook = by_name.loc["James Cook"]
    assert cook["adp"] == 9.5  # matched across the "III" suffix
    assert cook["points_2025"] == (200.0 + 260.0) / 2
    # Recency-weighted ppg: 70% 2025, 20% 2024, 10% 2023 (all full seasons).
    ppg = {2025: 230.0 / 17, 2024: 200.0 / 17, 2023: 190.0 / 16}
    expected = 0.7 * ppg[2025] + 0.2 * ppg[2024] + 0.1 * ppg[2023]
    assert cook["avg_ppg_3yr"] == round(expected, 2)
    # Only RB with stats+ADP -> the ADP-implied curve is just his own value,
    # so the 50/50 blend is a no-op here.
    assert cook["projected_points"] == round(expected * 17, 1)
    assert cook["injury_status"] == "Questionable"
    assert cook["status"] == "Active"

    # A defense has ADP but no stats -> fallback projection, still in the pool.
    dst = by_name.loc["Chicago Defense"]
    assert dst["adp"] == 130.0
    assert float(dst["projected_points"]) > 0


def test_build_dataset_sorted_by_projection():
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026,
        get_json=fake_get_json, read_csv=fake_read_csv, get_status_json=fake_get_status_json,
    )
    assert list(df["projected_points"]) == sorted(df["projected_points"], reverse=True)


def test_build_dataset_blends_projection_toward_this_years_adp():
    # Two WRs with stats: Chase outscored Cook historically, but this year's
    # ADP has Cook going ahead of Chase at the position (a camp battle won, a
    # new role, whatever the market has priced in that the 3yr stats can't).
    stat_years = [2023, 2024, 2025]
    adp_payload = {
        "status": "Success",
        "players": [
            {"name": "James Cook", "position": "WR", "team": "BUF", "adp": 5.0},
            {"name": "Ja'Marr Chase", "position": "WR", "team": "CIN", "adp": 20.0},
        ],
    }
    stats = {
        y: _stats_frame(y, [
            {"player_display_name": "James Cook", "position": "WR", "recent_team": "BUF",
             "games": 16, "fantasy_points": 60.0, "fantasy_points_ppr": 90.0},
            {"player_display_name": "Ja'Marr Chase", "position": "WR", "recent_team": "CIN",
             "games": 16, "fantasy_points": 200.0, "fantasy_points_ppr": 280.0},
        ])
        for y in stat_years
    }
    df = build_dataset(
        stat_years=stat_years, adp_year=2026,
        get_json=lambda url: adp_payload,
        read_csv=lambda url: stats[int(url.split("_")[-1].split(".")[0])].copy(),
        include_status=False,
    )
    by_name = df.set_index("player")
    cook_stats_only = round((90.0 + 60.0) / 2 / 16 * 17, 1)  # half-ppr, unblended
    chase_stats_only = round((280.0 + 200.0) / 2 / 16 * 17, 1)

    # Blended toward this year's ADP: Cook (ADP rank 1) pulled up, Chase
    # (ADP rank 2) pulled down, without either fully losing their own history.
    assert by_name.loc["James Cook", "projected_points"] > cook_stats_only
    assert by_name.loc["Ja'Marr Chase", "projected_points"] < chase_stats_only
    # But the market view doesn't fully override history either.
    assert by_name.loc["James Cook", "projected_points"] < chase_stats_only


def test_fetch_player_status_shapes_rows_and_dedupes():
    df = fetch_player_status(get_json=fake_get_status_json)
    assert set(df["player"]) == {"James Cook", "Ja'Marr Chase"}
    cook = df[df["player"] == "James Cook"].iloc[0]
    assert cook["injury_status"] == "Questionable"
    assert cook["status"] == "Active"
    assert cook["key"] == "james cook|RB"


def _write_pool(tmp_path, rows):
    path = tmp_path / "player_pool.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_load_adp_snapshot_reads_prior_pool(tmp_path):
    path = _write_pool(tmp_path, [
        {"player": "James Cook", "position": "RB", "team": "BUF", "adp": 9.5,
         "adp_stdev": 3.1, "times_drafted": 120, "bye": 7},
        {"player": "No Adp Guy", "position": "WR", "team": "NYJ", "adp": None,
         "adp_stdev": None, "times_drafted": None, "bye": None},
    ])
    snap = load_adp_snapshot(path)
    assert list(snap["player"]) == ["James Cook"]  # rows without ADP dropped
    row = snap.iloc[0]
    assert row["adp"] == 9.5 and row["adp_team"] == "BUF" and row["key"] == "james cook|RB"


def test_load_adp_snapshot_missing_file_is_empty(tmp_path):
    assert load_adp_snapshot(tmp_path / "nope.csv").empty


def test_build_dataset_falls_back_when_live_adp_is_thin(tmp_path):
    # Out of draft season FFC returns no players; the prior pool's ADP is reused.
    snap = load_adp_snapshot(_write_pool(tmp_path, [
        {"player": "James Cook", "position": "RB", "team": "BUF", "adp": 9.5},
        {"player": "Ja'Marr Chase", "position": "WR", "team": "CIN", "adp": 3.9},
    ]))
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026,
        get_json=lambda url: {"status": "Success", "players": []},
        read_csv=fake_read_csv, get_status_json=fake_get_status_json,
        adp_fallback=snap,
    )
    assert df.attrs["adp_source"] == "fallback"
    assert df.attrs["live_adp_players"] == 0
    assert df.set_index("player").loc["Ja'Marr Chase", "adp"] == 3.9


def test_build_dataset_prefers_live_adp_when_healthy(tmp_path):
    snap = load_adp_snapshot(_write_pool(tmp_path, [
        {"player": "James Cook", "position": "RB", "team": "BUF", "adp": 50.0},
    ]))
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026,
        get_json=fake_get_json, read_csv=fake_read_csv,
        get_status_json=fake_get_status_json,
        adp_fallback=snap, min_adp_players=2,
    )
    assert df.attrs["adp_source"] == "live"
    assert df.set_index("player").loc["James Cook", "adp"] == 9.5


def test_weighted_ppg_uses_70_20_10_for_full_seasons():
    ppg = {2025: 20.0, 2024: 10.0, 2023: 5.0}
    games = {2025: 17, 2024: 17, 2023: 17}
    assert _weighted_ppg(ppg, [2025, 2024, 2023], games) == pytest.approx(16.5)


def test_weighted_ppg_scales_down_short_seasons():
    # 2025 was a 4-game sample: weight 0.7 * 4/8 = 0.35, then renormalized.
    ppg = {2025: 30.0, 2024: 10.0, 2023: 10.0}
    games = {2025: 4, 2024: 17, 2023: 17}
    expected = (0.35 * 30.0 + 0.2 * 10.0 + 0.1 * 10.0) / (0.35 + 0.2 + 0.1)
    assert _weighted_ppg(ppg, [2025, 2024, 2023], games) == pytest.approx(expected)


def test_weighted_ppg_ignores_zero_game_seasons():
    ppg = {2025: 0.0, 2024: 12.0, 2023: 6.0}
    games = {2025: 0, 2024: 16, 2023: 16}
    expected = (0.2 * 12.0 + 0.1 * 6.0) / 0.3
    assert _weighted_ppg(ppg, [2025, 2024, 2023], games) == pytest.approx(expected)


def test_weighted_ppg_full_weight_at_eight_games():
    ppg = {2025: 20.0, 2024: 10.0, 2023: 5.0}
    eight = {2025: 8, 2024: 8, 2023: 8}
    full = {2025: 17, 2024: 17, 2023: 17}
    seasons = [2025, 2024, 2023]
    assert _weighted_ppg(ppg, seasons, eight) == pytest.approx(_weighted_ppg(ppg, seasons, full))


ROSTER_STATUS = {
    "1": {"full_name": "James Cook", "position": "RB", "team": "BUF", "active": True,
          "status": "Active"},
    # Retired: Sleeper still says Active, but he's on no team.
    "2": {"full_name": "Ja'Marr Chase", "position": "WR", "team": None, "active": True,
          "status": "Active"},
}


def test_build_dataset_keeps_only_rostered_players():
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026,
        get_json=fake_get_json, read_csv=fake_read_csv,
        get_status_json=lambda url: ROSTER_STATUS,
    )
    players = set(df["player"])
    assert "Ja'Marr Chase" not in players  # no NFL team -> off the board
    assert "James Cook" in players
    assert "Chicago Defense" in players  # team defenses always kept
    assert "ja'marr chase|WR".replace("'", "") in df.attrs["dropped_off_roster"]


def test_build_dataset_uses_sleeper_team_for_current_team():
    status = {"1": {**ROSTER_STATUS["1"], "team": "KC"}}
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026,
        get_json=fake_get_json, read_csv=fake_read_csv,
        get_status_json=lambda url: status,
    )
    assert df.set_index("player").loc["James Cook", "team"] == "KC"


def test_fetch_player_status_prefers_rostered_duplicate():
    payload = {
        "1": {"full_name": "Mike Williams", "position": "WR", "team": None,
              "active": False, "status": "Inactive"},
        "2": {"full_name": "Mike Williams", "position": "WR", "team": "PIT",
              "active": True, "status": "Active"},
    }
    df = fetch_player_status(get_json=lambda url: payload)
    assert list(df["nfl_team"]) == ["PIT"]


def test_build_dataset_docks_player_who_missed_last_season():
    stat_years = [2023, 2024, 2025]
    stats = {
        2023: _stats_frame(2023, [
            {"player_display_name": "Hurt Guy", "position": "RB", "recent_team": "BUF",
             "games": 17, "fantasy_points": 170.0, "fantasy_points_ppr": 170.0},
        ]),
        2024: _stats_frame(2024, [
            {"player_display_name": "Hurt Guy", "position": "RB", "recent_team": "BUF",
             "games": 17, "fantasy_points": 170.0, "fantasy_points_ppr": 170.0},
        ]),
        2025: _stats_frame(2025, [
            {"player_display_name": "Other Guy", "position": "WR", "recent_team": "BUF",
             "games": 17, "fantasy_points": 100.0, "fantasy_points_ppr": 100.0},
        ]),
    }
    df = build_dataset(
        stat_years=stat_years, adp_year=2026,
        get_json=lambda url: {"players": []},
        read_csv=lambda url: stats[int(url.split("_")[-1].split(".")[0])].copy(),
        include_status=False,
    )
    # 10 ppg history -> 170 pts, docked 20% for sitting out all of 2025.
    assert df.set_index("player").loc["Hurt Guy", "projected_points"] == 136.0
