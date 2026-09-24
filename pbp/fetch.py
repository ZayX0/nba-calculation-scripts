"""Fetch NBA play-by-play and cache the raw JSON under data/raw/{source}/{GAME_ID}.json.gz.

Usage:
    python -m pbp.fetch 0042500401 0042500402
    python -m pbp.fetch --season 2025-26 --season-type Playoffs
    python -m pbp.fetch --season 2025-26 --team HOU
    python -m pbp.fetch --help

Games already in the cache aren't downloaded again unless --refresh is given. Games that
haven't finished aren't cached.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import requests

from pbp import cache, client, sources

# FetchResult statuses.
CACHED = "cached"  # already on disk, so no request was made
FETCHED = "fetched"  # downloaded and saved
MISSING = "missing"  # the source says the game doesn't exist
IN_PROGRESS = "in_progress"  # the game hasn't finished, so it wasn't saved
ERROR = "error"  # the request failed after retries, or the response couldn't be read


@dataclass(frozen=True)
class FetchResult:
    game_id: str
    source: str
    status: str
    path: Path | None = None
    error: str | None = None

    def __str__(self) -> str:
        detail = self.path or self.error
        return f"{self.game_id} {self.source}: {self.status}" + (f" ({detail})" if detail else "")


def fetch_game(
    game_id: str,
    *,
    session: requests.Session,
    source: str | None = None,
    data_dir: Path = cache.DEFAULT_DATA_DIR,
    refresh: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """Download one game's play-by-play into the cache, unless it's already there.

    ``source`` defaults to the CDN for 2019-20 onward and stats.nba.com before that. Raises
    BlockedError if the bot filter blocks the request, and a requests exception if the request
    still fails after retries.
    """
    sources.validate_game_id(game_id)
    source = source or sources.default_source(game_id)
    path = cache.pbp_path(data_dir, source, game_id)
    if path.exists() and not refresh:
        return FetchResult(game_id, source, CACHED, path)
    response = client.get_with_retries(session, sources.pbp_url(source, game_id), sleep=sleep)
    payload = sources.parse_pbp(source, response)
    if payload is None:
        return FetchResult(game_id, source, MISSING)
    if not sources.is_final(source, payload):
        return FetchResult(game_id, source, IN_PROGRESS)
    cache.save(path, response.content)
    return FetchResult(game_id, source, FETCHED, path)


def fetch_games(
    game_ids: Iterable[str],
    *,
    session: requests.Session,
    source: str | None = None,
    data_dir: Path = cache.DEFAULT_DATA_DIR,
    refresh: bool = False,
    delay: float = 0.6,
    max_consecutive_errors: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> list[FetchResult]:
    """Download several games, waiting ``delay`` seconds between network requests.

    A game that fails is logged and skipped. A BlockedError stops the run at once, and so do
    ``max_consecutive_errors`` failures in a row, since later requests would likely fail too.
    """
    game_ids = [sources.validate_game_id(game_id) for game_id in game_ids]
    results: list[FetchResult] = []
    consecutive_errors = 0
    for i, game_id in enumerate(game_ids, 1):
        if results and results[-1].status != CACHED and delay:
            sleep(delay)
        try:
            result = fetch_game(
                game_id, session=session, source=source, data_dir=data_dir, refresh=refresh, sleep=sleep
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            # ValueError covers unreadable JSON; KeyError covers JSON in an unexpected shape.
            error = f"{type(exc).__name__}: {exc}"
            result = FetchResult(game_id, source or sources.default_source(game_id), ERROR, error=error)
        results.append(result)
        log(f"[{i}/{len(game_ids)}] {result}")
        consecutive_errors = consecutive_errors + 1 if result.status == ERROR else 0
        if consecutive_errors >= max_consecutive_errors:
            log(
                f"Stopping after {consecutive_errors} failures in a row. If stats.nba.com timed out, "
                "the bot filter is probably blocking requests; see CLAUDE.md."
            )
            break
    return results


def fetch_gamelog(
    season: str,
    season_type: str,
    *,
    session: requests.Session,
    data_dir: Path = cache.DEFAULT_DATA_DIR,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Download the list of a season's played games from stats.nba.com, and cache it.

    It's downloaded every time, since it grows as the season goes on. Read game IDs out of it
    with ``sources.parse_game_ids()``.
    """
    params = sources.gamelog_params(season, season_type)
    response = client.get_with_retries(session, sources.GAMELOG_URL, params=params, sleep=sleep)
    response.raise_for_status()
    gamelog = response.json()
    cache.save(cache.gamelog_path(data_dir, season, season_type), response.content)
    return gamelog


def season_game_ids(
    season: str,
    season_types: Iterable[str],
    teams: Iterable[str],
    *,
    session: requests.Session,
    data_dir: Path = cache.DEFAULT_DATA_DIR,
    log: Callable[[str], None] = print,
) -> list[str]:
    """The IDs of a season's played games of the given types, only for ``teams`` if any are given.

    Raises ValueError if one of the teams played none of those games, which usually means a
    mistyped abbreviation.
    """
    teams = list(teams)
    game_ids: list[str] = []
    teams_seen: set[str] = set()
    for season_type in season_types:
        gamelog = fetch_gamelog(season, season_type, session=session, data_dir=data_dir)
        ids = sources.parse_game_ids(gamelog, teams)
        teams_seen.update(sources.gamelog_teams(gamelog))
        count = f"{len(ids)} game" + ("" if len(ids) == 1 else "s")
        log(f"{season} {season_type}: {count}" + (f" for {', '.join(teams)}" if teams else ""))
        game_ids += ids
    unknown = [team for team in teams if team not in teams_seen]
    if unknown:
        raise ValueError(
            f"no {season} games for {', '.join(unknown)}. "
            f"Teams with games that season: {', '.join(sorted(teams_seen)) or 'none'}"
        )
    return game_ids


def main(argv: list[str] | None = None, *, session: requests.Session | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pbp.fetch", description="Download NBA play-by-play into data/raw/."
    )
    parser.add_argument(
        "game_ids", nargs="*", metavar="GAME_ID", help="10-digit NBA game IDs, e.g. 0042500401"
    )
    parser.add_argument(
        "--season",
        action="append",
        default=[],
        help="fetch every played game of a season, e.g. 2025-26 or 2025-2026 (repeatable)",
    )
    parser.add_argument(
        "--team",
        action="append",
        default=[],
        help="with --season, only that team's games, by abbreviation, e.g. HOU (repeatable)",
    )
    parser.add_argument(
        "--season-type",
        action="append",
        choices=sources.SEASON_TYPES,
        help='with --season, which games to fetch (repeatable; default "Regular Season")',
    )
    parser.add_argument(
        "--source",
        choices=("auto",) + sources.SOURCES,
        default="auto",
        help="auto (the default) uses the CDN for 2019-20 onward and stats.nba.com before that",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=cache.DEFAULT_DATA_DIR, help="default: data/ in the repo"
    )
    parser.add_argument("--refresh", action="store_true", help="download games again even if they're cached")
    parser.add_argument("--delay", type=float, default=0.6, help="seconds between requests (default 0.6)")
    args = parser.parse_args(argv)

    if not args.game_ids and not args.season:
        parser.error("give game IDs or --season")
    if args.season_type and not args.season:
        parser.error("--season-type needs --season")
    if args.team and not args.season:
        parser.error("--team needs --season")
    try:
        for game_id in args.game_ids:
            sources.validate_game_id(game_id)
        seasons = [sources.validate_season(season) for season in args.season]
    except ValueError as exc:
        parser.error(str(exc))
    teams = list(dict.fromkeys(team.upper() for team in args.team))

    session = session or client.make_session()
    source = None if args.source == "auto" else args.source
    game_ids = list(args.game_ids)
    try:
        for season in seasons:
            game_ids += season_game_ids(
                season, args.season_type or ["Regular Season"], teams, session=session, data_dir=args.data_dir
            )
        results = fetch_games(
            dict.fromkeys(game_ids),
            session=session,
            source=source,
            data_dir=args.data_dir,
            refresh=args.refresh,
            delay=args.delay,
        )
    except (sources.BlockedError, requests.RequestException, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    counts = Counter(result.status for result in results)
    print("Done: " + ", ".join(f"{count} {status}" for status, count in counts.items()))
    return 1 if counts[ERROR] else 0


if __name__ == "__main__":
    sys.exit(main())
