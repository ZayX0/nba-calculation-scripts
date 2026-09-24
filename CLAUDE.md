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

## Example questions

The calculation scripts should be able to answer questions like these. Under each one is the data
that answers it, checked against 2025-26 data on 2026-09-24. The NBA.com tracking endpoints named
below are on `stats.nba.com`, so the bot-filter setup further down applies to them. Like
play-by-play, they're fetched and cached by the data-access code.

### 1. How often does player X hit their shot when passed the ball by teammate Y?

- **Play-by-play only covers made shots.** A made shot names the passer in `assistPersonId` (CDN
  data), but a missed shot has no passer field. So play-by-play can count Y's assists to X, but
  not X's shooting percentage on Y's passes.
- **For the full answer, use NBA.com's pass tracking:** `stats.nba.com/stats/playerdashptpass`
  (`PlayerDashPtPass` in `nba_api`). Its "received" table has one row per teammate who passed to
  the player, with `PASS`, `AST`, `FGM`, `FGA`, `FG_PCT` and 2- and 3-point splits. These are
  totals for a season or date range, not individual plays.

### 2. How often does an opponent miss their shot when player X is within N feet?

- **Play-by-play can't answer this.** It has no defender positions. The only defensive events it
  records are blocks (`blockPersonId`) and steals.
- **Public tracking data only gets close:**
  - `playerdashptshotdefend` (`PlayerDashPtShotDefend`): opponents' shooting percentage on shots
    where X was the closest defender, next to those shooters' normal percentage. It's split by
    the shot's distance from the basket (under 6 ft, under 10 ft, over 15 ft, 2s and 3s), not by
    how close X was. Pass `team_id=0`; a real team ID returned no rows.
  - `leaguedashptdefend` (`LeagueDashPtDefend`): the same numbers for every player, one category
    at a time.
  - Closest-defender distance ranges (0-2, 2-4, 4-6 and 6+ ft) exist only per shooter
    (`PlayerDashPtShots`, table `ClosestDefenderShooting`) or per team's opponents
    (`LeagueDashOppPtShot`). They aren't available for a named defender.
- An exact "within N feet of player X" needs raw player-tracking coordinates, which aren't
  public. Any script answering this must say which approximation it uses.

### 3. What teammate combination produces the best plus-minus for the team?

- **Play-by-play can answer this, but you have to rebuild who was on court.** There's no field
  listing the players on court. Track substitution events (`actionType` `substitution`, with
  `subType` `in` or `out`). Work out who started each period, since starters aren't listed
  outside the first period: a player who appears in a period before subbing in started it. A
  player with no events all period won't show up this way, so check that each team always has
  exactly five on court.
- Credit each change in score to the five players each team had on court. Free throws count for
  the lineup on court when the foul happened, even if substitutions came between the foul and the
  shots. Then total the results for each 2-, 3-, 4- or 5-man combination.
- **Compare per 100 possessions (net rating), not raw plus-minus.** The CDN's `possession` field
  helps count possessions. Set a minimum-minutes threshold, because otherwise the "best" list
  fills up with combinations that barely played.
- Check the results against `teamdashlineups` (`TeamDashLineups`, `group_quantity` 2 to 5). It
  gives NBA.com's official `PLUS_MINUS` and `MIN` for each combination.

## Current state

Fetching and caching play-by-play works. Normalizing it into tables and the calculation scripts
are still to come. Keep this section up to date as the layout and commands change.

Layout:

- `pbp/`: fetching and caching play-by-play data. Normalizing will go here too.
  - `client.py`: the HTTP session that gets through NBA.com's bot filter, plus retries.
  - `sources.py`: source URLs, which source to use for a game, how to read responses, and
    whether a game has finished.
  - `cache.py`: where raw responses are stored, and how to read them back.
  - `fetch.py`: the command-line entry point, `python -m pbp.fetch`.
- `calculations/` (not created yet): probability and correlation scripts, one analysis per script.
- `data/`: the local cache of raw API responses, and later normalized tables. It's gitignored;
  never commit it.
- `README.md`: the human-facing overview: capabilities, requirements, setup, usage and
  troubleshooting. Update it when commands, options or requirements change.
- `tests/`: tests that run without the network. `tests/fixtures/` holds real responses saved on
  2026-09-24, with the play-by-play trimmed to its first and last few events.

Stack: Python 3.9 or newer (tested on 3.9 to 3.13) with `requests`, plus `pytest` for tests (see
`requirements.txt`). `pandas`, `numpy` and `scipy` are planned for the calculations.

Commands, run from the repo root:

```sh
pip install -r requirements.txt
pytest                                      # all tests; no network needed
python -m pbp.fetch 0042500401 0029600001   # specific games
python -m pbp.fetch --season 2025-26        # every played regular-season game (~17 min)
python -m pbp.fetch --season 2025-2026 --team HOU   # one team's games (~1 min)
python -m pbp.fetch --season 2025-26 --season-type Playoffs --season-type PlayIn
python -m pbp.fetch --help                  # --source, --refresh, --delay, --data-dir
```

`--season` accepts `2025-26` or `2025-2026` and lists a season's played games with
stats.nba.com's `leaguegamelog` endpoint. `--team` (repeatable) keeps only games involving those
teams. It takes the abbreviation the team used that season, such as `NJN` rather than `BKN` for
2010-11. An abbreviation with no games that season is an error that lists the valid ones, and
it's raised before any game is downloaded. By default, games from 2019-20 onward come from the
CDN and older games from stats.nba.com.

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
  `proxy_manager_for`. `pbp.client.make_session()` does all of this; use it for any NBA.com
  request, including the tracking endpoints.
- **If you use `nba_api` (v1.11.4):** neither endpoint works out of the box. Call
  `set_session()` on `NBAStatsHTTP` and `NBALiveHTTP` with a session built as above. Also pass
  the full header set with `headers=` to the live endpoints, since `nba_api`'s default live
  headers are rejected.

### Games that don't exist

A game that was never played, such as Finals game 6 in a series that ended in five, comes back
differently from each source:

- The CDN returns **403 with an XML body** (`<Code>AccessDenied</Code>`), not 404. A 403 with an
  HTML "Access Denied" page is the bot filter instead, for existing and missing games alike.
- stats.nba.com returns **200 with an empty `actions` list**.

Treat both as "no such game", not as an error to retry. `pbp/sources.py` handles both, and raises
`BlockedError` on the bot filter's HTML page.

### Games that haven't finished

The CDN ends a finished game with an `actionType` `game`, `subType` `end` event. stats.nba.com
has no such event; its last event is the final period's end. So a stats.nba.com game counts as
finished when its last event is a `period` `end` in period 4 or later and the score isn't tied.
This was checked on games from 1996-97 to 2025-26, including overtime games. Games that haven't
finished aren't cached.

## Conventions for fetching code

- Cache every raw response on disk and reuse it. `pbp/cache.py` stores each one byte for byte,
  gzip-compressed, at `data/raw/{source}/{GAME_ID}.json.gz`, and season game lists at
  `data/raw/gamelog/{season}_{season_type}.json.gz`. Read them back with `cache.read_json()`.
  Gzip matters here: a game averages about 430 KB uncompressed and 33 KB gzipped, so a season
  takes about 40 MB instead of 530 MB. A finished game's play-by-play rarely changes, so fetch
  each game once.
- Retry timeouts, connection errors and 429 or 5xx responses with exponential backoff. Pause
  briefly between requests: 0.6 s by default.
- Keep the raw JSON. Normalize it into one table per game (game, period, clock, team, player,
  action type, score) in a separate step, so the parsing can change without fetching again.
- Tests use saved JSON fixtures and a fake session (`tests/fakes.py`), not live requests.

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
