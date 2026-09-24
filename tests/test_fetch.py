import gzip
import json

import pytest
import requests

from fakes import FakeResponse, FakeSession, Sleeper, fixture_bytes, fixture_json, ok
from pbp import cache, fetch, sources

CDN_GAME = "cdn_playbyplay_0042500401.json"
STATS_GAME = "stats_playbyplayv3_0042500401.json"


def in_progress_cdn_game() -> FakeResponse:
    payload = fixture_json(CDN_GAME)
    payload["game"]["actions"].pop()  # no "Game End" yet
    return FakeResponse(200, json.dumps(payload).encode())


def test_fetches_then_reuses_the_cache(tmp_path):
    session = FakeSession(ok(CDN_GAME))
    first = fetch.fetch_game("0042500401", session=session, data_dir=tmp_path)
    assert first.status == fetch.FETCHED
    assert first.path == tmp_path / "raw" / "cdn" / "0042500401.json.gz"
    assert gzip.decompress(first.path.read_bytes()) == fixture_bytes(CDN_GAME)  # the raw response
    assert cache.read_json(first.path) == fixture_json(CDN_GAME)

    second = fetch.fetch_game("0042500401", session=session, data_dir=tmp_path)
    assert second.status == fetch.CACHED
    assert len(session.calls) == 1


def test_refresh_downloads_again(tmp_path):
    session = FakeSession(ok(CDN_GAME), ok(CDN_GAME))
    fetch.fetch_game("0042500401", session=session, data_dir=tmp_path)
    result = fetch.fetch_game("0042500401", session=session, data_dir=tmp_path, refresh=True)
    assert result.status == fetch.FETCHED
    assert len(session.calls) == 2


def test_older_games_come_from_stats_nba_com(tmp_path):
    session = FakeSession(ok(STATS_GAME))
    result = fetch.fetch_game("0021800001", session=session, data_dir=tmp_path)
    assert result.source == sources.STATS
    assert session.calls[0][0].startswith("https://stats.nba.com/stats/playbyplayv3?GameID=0021800001")


def test_missing_and_in_progress_games_are_not_cached(tmp_path):
    session = FakeSession(
        FakeResponse(403, fixture_bytes("cdn_403_missing_game.xml")), in_progress_cdn_game()
    )
    assert fetch.fetch_game("0042500406", session=session, data_dir=tmp_path).status == fetch.MISSING
    assert fetch.fetch_game("0042500401", session=session, data_dir=tmp_path).status == fetch.IN_PROGRESS
    assert not (tmp_path / "raw").exists()


def test_fetch_games_waits_only_between_network_requests(tmp_path):
    session = FakeSession(ok(CDN_GAME), ok(CDN_GAME))
    sleep = Sleeper()
    fetch.fetch_game("0042500401", session=FakeSession(ok(CDN_GAME)), data_dir=tmp_path)  # pre-cache game 1
    results = fetch.fetch_games(
        ["0042500401", "0042500402", "0042500403"],
        session=session,
        data_dir=tmp_path,
        delay=0.5,
        sleep=sleep,
        log=lambda line: None,
    )
    assert [r.status for r in results] == [fetch.CACHED, fetch.FETCHED, fetch.FETCHED]
    assert sleep.waits == [0.5]  # none after the cache hit, one between the two downloads


def test_fetch_games_skips_a_failed_game(tmp_path):
    session = FakeSession(FakeResponse(200, b"not json"), ok(CDN_GAME))
    lines = []
    results = fetch.fetch_games(
        ["0042500401", "0042500402"], session=session, data_dir=tmp_path, sleep=Sleeper(), log=lines.append
    )
    assert [r.status for r in results] == [fetch.ERROR, fetch.FETCHED]
    assert "error" in lines[0]


def test_fetch_games_stops_after_repeated_failures(tmp_path):
    session = FakeSession(*[requests.Timeout()] * 20)
    lines = []
    results = fetch.fetch_games(
        ["0021800001", "0021800002", "0021800003", "0021800004"],
        session=session,
        data_dir=tmp_path,
        max_consecutive_errors=2,
        sleep=Sleeper(),
        log=lines.append,
    )
    assert [r.status for r in results] == [fetch.ERROR, fetch.ERROR]
    assert "Stopping" in lines[-1]


def test_fetch_games_stops_at_once_when_blocked(tmp_path):
    session = FakeSession(FakeResponse(403, fixture_bytes("cdn_403_blocked.html")))
    with pytest.raises(sources.BlockedError):
        fetch.fetch_games(
            ["0042500401", "0042500402"], session=session, data_dir=tmp_path, log=lambda line: None
        )


GAMELOG = "leaguegamelog_2025-26_playoffs.json"


def test_fetch_gamelog_caches_the_game_list(tmp_path):
    session = FakeSession(ok(GAMELOG))
    gamelog = fetch.fetch_gamelog("2025-26", "Playoffs", session=session, data_dir=tmp_path)
    assert gamelog == fixture_json(GAMELOG)
    assert session.calls[0][1]["SeasonType"] == "Playoffs"
    assert (tmp_path / "raw" / "gamelog" / "2025-26_playoffs.json.gz").exists()


def test_season_game_ids_for_the_whole_league_or_some_teams(tmp_path):
    lines = []
    session = FakeSession(ok(GAMELOG), ok(GAMELOG))
    all_ids = fetch.season_game_ids(
        "2025-26", ["Playoffs"], [], session=session, data_dir=tmp_path, log=lines.append
    )
    hou_ids = fetch.season_game_ids(
        "2025-26", ["Playoffs"], ["HOU"], session=session, data_dir=tmp_path, log=lines.append
    )
    assert all_ids == ["0042500121", "0042500131", "0042500161", "0042500171"]
    assert hou_ids == ["0042500171"]
    assert lines == ["2025-26 Playoffs: 4 games", "2025-26 Playoffs: 1 game for HOU"]


def test_season_game_ids_rejects_a_team_with_no_games(tmp_path):
    session = FakeSession(ok(GAMELOG))
    with pytest.raises(
        ValueError, match=r"no 2025-26 games for HUO\. Teams with games that season: ATL, CLE"
    ):
        fetch.season_game_ids(
            "2025-26", ["Playoffs"], ["HOU", "HUO"], session=session, data_dir=tmp_path, log=lambda line: None
        )


def test_cli_fetches_a_season(tmp_path, capsys):
    session = FakeSession(ok(GAMELOG), *[ok(CDN_GAME)] * 4)
    code = fetch.main(
        ["--season", "2025-26", "--season-type", "Playoffs", "--data-dir", str(tmp_path), "--delay", "0"],
        session=session,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "2025-26 Playoffs: 4 games" in out
    assert "Done: 4 fetched" in out


def test_cli_fetches_one_teams_games(tmp_path, capsys):
    session = FakeSession(ok(GAMELOG), ok(CDN_GAME))
    argv = [
        "--season",
        "2025-2026",
        "--season-type",
        "Playoffs",
        "--team",
        "hou",
        "--data-dir",
        str(tmp_path),
    ]
    assert fetch.main(argv, session=session) == 0
    out = capsys.readouterr().out
    assert "2025-26 Playoffs: 1 game for HOU" in out
    assert "0042500171 cdn: fetched" in out
    assert session.calls[0][1]["Season"] == "2025-26"
    assert len(session.calls) == 2  # the game list, then HOU's one game


def test_cli_reports_an_unknown_team_before_fetching_games(tmp_path, capsys):
    session = FakeSession(ok(GAMELOG))
    argv = ["--season", "2025-26", "--season-type", "Playoffs", "--team", "XYZ", "--data-dir", str(tmp_path)]
    assert fetch.main(argv, session=session) == 1
    assert "no 2025-26 games for XYZ" in capsys.readouterr().err
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["123"],
        ["--season", "2025"],
        ["--season-type", "Playoffs", "0042500401"],
        ["--team", "HOU", "0042500401"],
    ],
)
def test_cli_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit) as exc:
        fetch.main(argv, session=FakeSession())
    assert exc.value.code == 2
