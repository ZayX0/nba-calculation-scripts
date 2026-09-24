# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Purpose and direction

This repo holds scripts for NBA analysis, built in two stages:

1. **Data access (current focus):** scripts that fetch NBA play-by-play data and cache it locally.
2. **Calculations (planned):** scripts that use the cached data to calculate probability and
   correlation statistics for teams across a season. For example, how likely an outcome is given
   the game state, or how a team's metrics correlate with each other or with other teams' metrics
   over the schedule.

Keep these two stages separate. Only the data-access code calls the network. Calculation scripts
read cached or normalized data and must never call an API directly, so their results can be
reproduced offline.

## Current state

The repo only has `LICENSE` so far. There's no code, dependency file, test suite or build command
yet. When you add the first code, update this file with the real layout and the commands to run
it and its tests.

Planned layout. Adjust it once real code exists:

- `pbp/`: fetching, caching and normalizing play-by-play data
- `calculations/`: probability and correlation scripts, one analysis per script
- `data/`: local cache of raw API responses and normalized tables. Gitignore it and never commit
  it.
- `tests/`: tests for parsing and calculations. Use saved JSON fixtures, not live API calls.

Planned stack: Python 3 with `requests`, `pandas`, `numpy` and `scipy`. Add a `requirements.txt`
or `pyproject.toml` with the first code.

## Play-by-play data sources

All of these were tested and working on 2026-09-24. Each game's ID is a 10-digit string. Examples
checked:

- `0022500001`: 2025-26 regular season, game 1. Format: `002` + season start year `YY` + game
  number.
- `0042500401`: 2025-26 playoffs, round 4 (the Finals), game 1. Format: `004` + `YY` + `00` +
  round + series + game.

| Source | URL | Seasons | Notes |
|---|---|---|---|
| **NBA CDN** (primary) | `https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{GAME_ID}.json` | 2019-20 onward | The richest data. Events are in `game.actions`, with `possession`, `timeActual` (a real-world timestamp), `x`/`y` court coordinates and `qualifiers` |
| **stats.nba.com PlayByPlayV3** (use for older seasons) | `https://stats.nba.com/stats/playbyplayv3?GameID={GAME_ID}&StartPeriod=0&EndPeriod=0` | 1996-97 onward | Events are in `game.actions`, with `teamTricode`, `playerName`, `shotDistance` and `shotResult`. Don't use `PlayByPlayV2`, which now returns empty JSON |
| **ESPN** (backup) | `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={ESPN_EVENT_ID}` | Complete from about 2010 onward | Events are in `plays`. It uses ESPN's own event IDs; look them up with `.../nba/scoreboard?dates=YYYYMMDD`. Needs no special headers |
| BALLDONTLIE | `https://api.balldontlie.io/v1/plays?game_id={id}` | 2025 season onward | Needs an API key. Not tested yet |

The two NBA sources use mostly the same field names: `actionNumber`, `actionType`, `subType`,
`clock`, `period`, `personId`, `scoreHome` and `scoreAway`. `clock` is an ISO-8601 duration such
as `PT11M55.00S`, meaning 11:55 left in the period. For a given game, the CDN returns more events
than stats.nba.com, so don't mix the two sources within one game.

## Getting through the NBA's bot filter

Both `cdn.nba.com` and `stats.nba.com` sit behind Akamai's bot filter:

- **Send nearly the full set of Chrome headers:** `User-Agent` (Chrome 140), `Accept`,
  `Accept-Language`, `Accept-Encoding: gzip, deflate`, `Origin: https://www.nba.com`,
  `Referer: https://www.nba.com/`, `Sec-Ch-Ua`, `Sec-Ch-Ua-Mobile`, `Sec-Ch-Ua-Platform`,
  `Sec-Fetch-Dest: empty`, `Sec-Fetch-Mode: cors` and `Sec-Fetch-Site: same-site`. Sending only
  `User-Agent` and `Referer` isn't enough.
- **What happens without them:** the CDN returns a 403 "Access Denied" HTML page. stats.nba.com
  doesn't refuse; it just hangs until the request times out. A timeout from stats.nba.com
  usually means the request was blocked. Fix the headers before assuming the API is flaky.
- **In Python, use standard TLS settings with `requests`.** Akamai rejects urllib3's TLS
  settings even when the headers are correct. Mount an `HTTPAdapter` that passes
  `ssl_context=ssl.create_default_context()` in both `init_poolmanager` and
  `proxy_manager_for`.
- **If you use `nba_api` (v1.11.4):** neither endpoint works out of the box. Call
  `set_session()` on `NBAStatsHTTP` and `NBALiveHTTP` with a session built as above. Also pass
  the full header set with `headers=` to the live endpoints, since `nba_api`'s default live
  headers are rejected.

### Games that don't exist

A game that was never played, such as Finals game 6 in a series that ended in five, comes back
differently from each source:

- The CDN returns **403**, not 404.
- stats.nba.com returns **200 with an empty `actions` list**.

Treat both as "no such game", not as an error to retry.

## Conventions for fetching code

- Cache every raw response on disk, for example at `data/raw/{source}/{GAME_ID}.json`, and reuse
  it. A finished game's play-by-play rarely changes, so fetch each game once.
- Retry with exponential backoff and pause briefly between requests.
- Keep the raw JSON. Normalize it into one table per game (game, period, clock, team, player,
  action type, score) in a separate step, so the parsing can change without fetching again.
- Tests use saved JSON fixtures, not live requests.

## Conventions for calculation scripts

- Each script says in its docstring or output which seasons, season types and games it
  covers.
- Report the sample size (number of games or events) with every probability and correlation.
- Name the method, such as Pearson or Spearman correlation, or the probability model used. List
  any assumptions.
- A predictive calculation (for example, the chance a team wins given the game state at a
  moment) only uses information available at that moment. Never use later events in the same
  game or season.
- Set a fixed random seed wherever randomness is used, so results can be reproduced.

## Claude Code cloud sessions

- The environment's network policy must allow `cdn.nba.com`, `stats.nba.com`,
  `site.api.espn.com` and, if used, `api.balldontlie.io`.
- Outbound HTTPS goes through a proxy whose CA is set in `SSL_CERT_FILE` and
  `REQUESTS_CA_BUNDLE`. `ssl.create_default_context()` picks that up on its own. Never turn off
  TLS verification.
