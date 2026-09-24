import copy

import pytest
import requests

from fakes import FakeResponse, fixture_bytes, fixture_json
from pbp import sources

CDN_GAME = "cdn_playbyplay_0042500401.json"
STATS_GAME = "stats_playbyplayv3_0042500401.json"
STATS_UNPLAYED = "stats_playbyplayv3_0042500406_unplayed.json"


@pytest.mark.parametrize(
    "game_id, year", [("0022500001", 2025), ("0042500401", 2025), ("0029600001", 1996), ("0020000001", 2000)]
)
def test_season_start_year(game_id, year):
    assert sources.season_start_year(game_id) == year


@pytest.mark.parametrize("game_id", ["22500001", "0022500001x", "1022500001", "abcdefghij", ""])
def test_rejects_malformed_game_ids(game_id):
    with pytest.raises(ValueError):
        sources.validate_game_id(game_id)


def test_default_source_uses_cdn_from_2019_20():
    assert sources.default_source("0021900001") == sources.CDN
    assert sources.default_source("0042500401") == sources.CDN
    assert sources.default_source("0021800001") == sources.STATS
    assert sources.default_source("0029600001") == sources.STATS


def test_pbp_urls():
    assert sources.pbp_url(sources.CDN, "0042500401") == (
        "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0042500401.json"
    )
    assert sources.pbp_url(sources.STATS, "0042500401") == (
        "https://stats.nba.com/stats/playbyplayv3?GameID=0042500401&StartPeriod=0&EndPeriod=0"
    )


def test_parse_returns_payload_for_a_played_game():
    for source, name in [(sources.CDN, CDN_GAME), (sources.STATS, STATS_GAME)]:
        payload = sources.parse_pbp(source, FakeResponse(200, fixture_bytes(name)))
        assert payload["game"]["gameId"] == "0042500401"


def test_cdn_missing_game_is_a_403_with_an_xml_body():
    response = FakeResponse(403, fixture_bytes("cdn_403_missing_game.xml"))
    assert sources.parse_pbp(sources.CDN, response) is None


def test_cdn_block_is_a_403_with_an_html_page():
    response = FakeResponse(403, fixture_bytes("cdn_403_blocked.html"))
    with pytest.raises(sources.BlockedError):
        sources.parse_pbp(sources.CDN, response)


def test_stats_missing_game_is_a_200_with_no_actions():
    assert sources.parse_pbp(sources.STATS, FakeResponse(200, fixture_bytes(STATS_UNPLAYED))) is None


def test_parse_raises_on_other_errors():
    with pytest.raises(requests.HTTPError):
        sources.parse_pbp(sources.STATS, FakeResponse(500, b"oops"))
    with pytest.raises(requests.HTTPError):
        sources.parse_pbp(sources.CDN, FakeResponse(404, b"not found"))


def test_cdn_game_is_final_only_with_a_game_end_event():
    payload = fixture_json(CDN_GAME)
    assert sources.is_final(sources.CDN, payload)
    payload["game"]["actions"].pop()  # drop "Game End"
    assert not sources.is_final(sources.CDN, payload)


def test_stats_game_is_final_after_period_4_or_later_with_no_tie():
    payload = fixture_json(STATS_GAME)
    assert sources.is_final(sources.STATS, payload)

    tied = copy.deepcopy(payload)
    for action in tied["game"]["actions"]:
        if action["scoreHome"]:
            action["scoreAway"] = action["scoreHome"]
    assert not sources.is_final(sources.STATS, tied)  # heading to overtime

    third_quarter = copy.deepcopy(payload)
    third_quarter["game"]["actions"][-1]["period"] = 3
    assert not sources.is_final(sources.STATS, third_quarter)

    mid_period = copy.deepcopy(payload)
    mid_period["game"]["actions"].pop()  # drop "End of 4th Period"
    assert not sources.is_final(sources.STATS, mid_period)


def test_stats_final_check_skips_blank_scores():
    payload = fixture_json(STATS_GAME)
    last = payload["game"]["actions"][-1]
    last["scoreHome"] = last["scoreAway"] = ""
    assert sources.is_final(sources.STATS, payload)


@pytest.mark.parametrize(
    "season, label",
    [
        ("2025-26", "2025-26"),
        ("1999-00", "1999-00"),
        ("1996-97", "1996-97"),
        ("2025-2026", "2025-26"),
        ("1999-2000", "1999-00"),
    ],
)
def test_accepts_season_labels(season, label):
    assert sources.validate_season(season) == label


@pytest.mark.parametrize("season", ["2025", "2025-27", "2025-2027", "25-26", "2025/26", "2025-026"])
def test_rejects_bad_season_labels(season):
    with pytest.raises(ValueError):
        sources.validate_season(season)


def test_gamelog_params_reject_unknown_season_type():
    with pytest.raises(ValueError):
        sources.gamelog_params("2025-26", "Finals")


def test_parse_game_ids_deduplicates_team_rows():
    game_ids = sources.parse_game_ids(fixture_json("leaguegamelog_2025-26_playoffs.json"))
    assert game_ids == ["0042500121", "0042500131", "0042500161", "0042500171"]


def test_parse_game_ids_filters_by_team():
    gamelog = fixture_json("leaguegamelog_2025-26_playoffs.json")
    assert sources.parse_game_ids(gamelog, ["HOU"]) == ["0042500171"]
    assert sources.parse_game_ids(gamelog, ["HOU", "CLE"]) == ["0042500131", "0042500171"]
    assert sources.parse_game_ids(gamelog, ["SAS"]) == []


def test_gamelog_teams():
    teams = sources.gamelog_teams(fixture_json("leaguegamelog_2025-26_playoffs.json"))
    assert teams == ["ATL", "CLE", "DEN", "HOU", "LAL", "TOR"]
