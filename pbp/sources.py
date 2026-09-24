"""Play-by-play sources: their URLs, which one to use for a game, and how to read responses.

Two NBA.com sources are supported (see "Play-by-play data sources" in CLAUDE.md):

- ``cdn``: cdn.nba.com liveData, 2019-20 onward. The richest data.
- ``stats``: stats.nba.com PlayByPlayV3, 1996-97 onward.
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

CDN = "cdn"
STATS = "stats"
SOURCES = (CDN, STATS)

# The CDN has play-by-play from the 2019-20 season on; older games return 403.
CDN_FIRST_SEASON = 2019

_URLS = {
    CDN: "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json",
    STATS: "https://stats.nba.com/stats/playbyplayv3?GameID={game_id}&StartPeriod=0&EndPeriod=0",
}

GAMELOG_URL = "https://stats.nba.com/stats/leaguegamelog"
SEASON_TYPES = ("Regular Season", "Playoffs", "PlayIn")

_GAME_ID = re.compile(r"^00\d{8}$")
_SEASON = re.compile(r"^(\d{4})-(\d{2}|\d{4})$")


class BlockedError(RuntimeError):
    """NBA.com's bot filter rejected the request, so retrying won't help."""


def validate_game_id(game_id: str) -> str:
    """Return the game ID if it's a 10-digit NBA game ID such as 0022500001, else raise."""
    if not _GAME_ID.match(game_id):
        raise ValueError(f"not an NBA game ID (expected 10 digits starting with 00): {game_id!r}")
    return game_id


def season_start_year(game_id: str) -> int:
    """The year a game's season started: 0022500001 -> 2025, 0029600001 -> 1996."""
    yy = int(validate_game_id(game_id)[3:5])
    return 1900 + yy if yy >= 46 else 2000 + yy


def default_source(game_id: str) -> str:
    """The CDN for 2019-20 onward, stats.nba.com for older games."""
    return CDN if season_start_year(game_id) >= CDN_FIRST_SEASON else STATS


def pbp_url(source: str, game_id: str) -> str:
    return _URLS[source].format(game_id=validate_game_id(game_id))


def parse_pbp(source: str, response: requests.Response) -> dict | None:
    """Return a play-by-play response's JSON, or None if the game doesn't exist.

    The CDN answers a missing game with a 403 and an XML error body. A 403 with an HTML page is
    the bot filter instead, which raises BlockedError. stats.nba.com answers a missing game with
    a 200 and an empty ``actions`` list.
    """
    if source == CDN and response.status_code == 403:
        if b"<Code>AccessDenied</Code>" in response.content:
            return None
        raise BlockedError(
            f"cdn.nba.com's bot filter blocked the request for {response.url}. "
            "Check the headers and TLS setup in pbp/client.py against CLAUDE.md."
        )
    response.raise_for_status()
    payload = response.json()
    if not payload["game"]["actions"]:
        return None
    return payload


def is_final(source: str, payload: dict) -> bool:
    """Whether the play-by-play covers a finished game, so it's safe to cache.

    The CDN ends a finished game with a "game end" event. stats.nba.com has no such event, so a
    game counts as finished when its last event ends period 4 or later and the score isn't tied.
    """
    actions = payload["game"]["actions"]
    if not actions:
        return False
    last = actions[-1]
    if source == CDN:
        return last["actionType"] == "game" and last["subType"] == "end"
    if not (last["actionType"] == "period" and last["subType"] == "end" and last["period"] >= 4):
        return False
    # stats.nba.com leaves the score blank on some non-scoring events.
    for action in reversed(actions):
        home, away = str(action.get("scoreHome", "")), str(action.get("scoreAway", ""))
        if home and away:
            return home != away
    return False


def validate_season(season: str) -> str:
    """Return a season label in NBA.com's form, such as 2025-26, else raise.

    Accepts 2025-26 or 2025-2026.
    """
    match = _SEASON.match(season)
    if match:
        start, end = int(match[1]), match[2]
        expected = f"{start + 1}" if len(end) == 4 else f"{(start + 1) % 100:02d}"
        if end == expected:
            return f"{start}-{(start + 1) % 100:02d}"
    raise ValueError(f"not a season label like 2025-26 or 2025-2026: {season!r}")


def gamelog_params(season: str, season_type: str) -> dict:
    """Query parameters for stats.nba.com's leaguegamelog, which lists a season's played games."""
    if season_type not in SEASON_TYPES:
        raise ValueError(f"season type must be one of {SEASON_TYPES}: {season_type!r}")
    return {
        "Counter": 0,
        "Direction": "ASC",
        "LeagueID": "00",
        "PlayerOrTeam": "T",
        "Season": validate_season(season),
        "SeasonType": season_type,
        "Sorter": "DATE",
    }


def parse_game_ids(gamelog: dict, teams: Iterable[str] = ()) -> list[str]:
    """The unique game IDs in a leaguegamelog response, sorted.

    The response has one row per team per game. If ``teams`` are given (abbreviations such as
    HOU), only games those teams played in are returned.
    """
    teams = set(teams)
    result = gamelog["resultSets"][0]
    game_column = result["headers"].index("GAME_ID")
    team_column = result["headers"].index("TEAM_ABBREVIATION")
    return sorted({row[game_column] for row in result["rowSet"] if not teams or row[team_column] in teams})


def gamelog_teams(gamelog: dict) -> list[str]:
    """The abbreviations of the teams in a leaguegamelog response, sorted."""
    result = gamelog["resultSets"][0]
    team_column = result["headers"].index("TEAM_ABBREVIATION")
    return sorted({row[team_column] for row in result["rowSet"]})
