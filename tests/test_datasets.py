import pandas as pd

from fantasy_draft_tool.datasets import build_dataset, fetch_adp, fetch_seasonal_stats

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
        get_json=fake_get_json, read_csv=fake_read_csv,
    )
    by_name = df.set_index("player")

    cook = by_name.loc["James Cook"]
    assert cook["adp"] == 9.5  # matched across the "III" suffix
    assert cook["points_2025"] == (200.0 + 260.0) / 2
    # Recency-weighted ppg: 2025 counts 3x, 2024 2x, 2023 1x.
    ppg = {2025: 230.0 / 17, 2024: 200.0 / 17, 2023: 190.0 / 16}
    expected = (3 * ppg[2025] + 2 * ppg[2024] + 1 * ppg[2023]) / 6
    assert cook["avg_ppg_3yr"] == round(expected, 2)
    assert cook["projected_points"] == round(expected * 17, 1)

    # A defense has ADP but no stats -> fallback projection, still in the pool.
    dst = by_name.loc["Chicago Defense"]
    assert dst["adp"] == 130.0
    assert float(dst["projected_points"]) > 0


def test_build_dataset_sorted_by_projection():
    df = build_dataset(
        stat_years=[2023, 2024, 2025], adp_year=2026,
        get_json=fake_get_json, read_csv=fake_read_csv,
    )
    assert list(df["projected_points"]) == sorted(df["projected_points"], reverse=True)
