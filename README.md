# nba-calculation-scripts

Scripts for analyzing NBA play-by-play data.

The repo is built in two stages:

1. **Data access (available now):** a command that downloads play-by-play for NBA games, seasons
   or single teams from NBA.com, and saves it locally.
2. **Calculations (planned):** scripts that work only on the saved data to calculate probability
   and correlation statistics for teams across a season.

## What it can do

`python -m pbp.fetch` downloads every event in a game (shots, rebounds, fouls, substitutions,
the score after each play and more) and saves it on your machine. With it you can:

- **Fetch specific games** by NBA game ID.
- **Fetch a whole season:** regular season, playoffs and/or play-in.
- **Fetch one team's season**, for example `--season 2025-2026 --team HOU`.
- **Go back to 1996-97.** The data source is chosen automatically:

  | Seasons | Source | Notes |
  |---|---|---|
  | 2019-20 onward | NBA's CDN (`cdn.nba.com`) | The richest data: possession, real-world timestamps, court x/y coordinates and play qualifiers |
  | 1996-97 onward | `stats.nba.com` (PlayByPlayV3) | Used for seasons before 2019-20 |

- **Download each game only once.** Later runs reuse the saved copy unless you pass `--refresh`.
  Games that haven't finished aren't saved, so you never end up with a partial game.
- **Keep the raw data.** Each response is stored exactly as NBA.com sent it, gzip-compressed, so
  future analysis scripts can re-read it without downloading again.

## Requirements

- **Python 3.9 or newer.** Tested on 3.9, 3.10, 3.11, 3.12 and 3.13.
- **Python packages:** `requests`, plus `pytest` to run the tests. Both are in `requirements.txt`.
- **Internet access** to `cdn.nba.com` and `stats.nba.com`. No API key or account is needed.
- **Disk space:** about 33 KB per game, which is about 40 MB for a full regular season (1,230
  games) or about 3 MB for one team's regular season.
- **Time:** about 0.8 seconds per game, because the script waits briefly between requests to be
  polite to NBA.com. A full regular season takes about 17 minutes and one team's season about a
  minute.

## Setup

```sh
git clone https://github.com/ZayX0/nba-calculation-scripts.git
cd nba-calculation-scripts
python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Check that everything works (the tests don't need a network connection):

```sh
pytest
```

## Usage

Run commands from the repo root.

```sh
# Specific games, by NBA game ID
python -m pbp.fetch 0042500401 0029600001

# One team's regular season
python -m pbp.fetch --season 2025-2026 --team HOU

# One team's regular season and playoffs
python -m pbp.fetch --season 2025-26 --team HOU --season-type "Regular Season" --season-type Playoffs

# Every game of a season
python -m pbp.fetch --season 2025-26

# All options
python -m pbp.fetch --help
```

Example output:

```text
2025-26 Regular Season: 82 games for HOU
[1/82] 0022500001 cdn: fetched (.../data/raw/cdn/0022500001.json.gz)
[2/82] 0022500012 cdn: fetched (.../data/raw/cdn/0022500012.json.gz)
...
Done: 82 fetched
```

| Option | What it does |
|---|---|
| `GAME_ID ...` | Games to fetch, such as `0042500401`. |
| `--season 2025-26` | Every played game of a season. `2025-2026` also works. Repeatable. |
| `--season-type` | With `--season`: `"Regular Season"` (the default), `Playoffs` or `PlayIn`. Repeatable. |
| `--team HOU` | With `--season`: only games involving that team. Repeatable. |
| `--source` | `auto` (the default), `cdn` or `stats`, to force a data source. |
| `--refresh` | Download games again even if they're already saved. |
| `--delay` | Seconds to wait between requests. The default is 0.6. |
| `--data-dir` | Where to save data. The default is `data/` in the repo. |

### Team abbreviations

`--team` takes the abbreviation the team used in that season, for example `NJN` rather than
`BKN` for the Nets in 2010-11. If an abbreviation has no games that season, the command stops
before downloading anything and lists the valid ones.

### Game IDs

A game ID is 10 digits:

- `0022500001`: regular season (`002`), season starting in 2025 (`25`), game 1 (`00001`).
- `0042500401`: playoffs (`004`), 2025-26, round 4 (the Finals), series 0, game 1.
- `0052500101`: play-in (`005`), 2025-26.

## Where the data goes

Downloads are saved under `data/`, which git ignores:

```text
data/raw/cdn/{GAME_ID}.json.gz                  # play-by-play, 2019-20 onward
data/raw/stats/{GAME_ID}.json.gz                # play-by-play, before 2019-20
data/raw/gamelog/{season}_{season_type}.json.gz # the list of games in a season
```

To read a saved game in Python:

```python
from pbp import cache

path = cache.pbp_path(cache.DEFAULT_DATA_DIR, "cdn", "0042500401")
game = cache.read_json(path)
for action in game["game"]["actions"][:4]:
    print(action["period"], action["clock"], action["description"])
```

```text
1 PT12M00.00S Period Start
1 PT11M55.00S Jump Ball K. Towns vs. V. Wembanyama: Tip to J. Hart
1 PT11M45.00S J. Brunson 25' 3PT  (3 PTS) (K. Towns 1 AST)
1 PT11M22.00S V. Wembanyama 15' pullup Jump Shot (2 PTS)
```

`clock` is the time left in the period, written as an ISO-8601 duration: `PT11M45.00S` means
11:45.

## Troubleshooting

- **`error: cdn.nba.com's bot filter blocked the request`, or stats.nba.com requests time out
  until the run stops after 3 failures:** NBA.com filters out requests that don't look like
  they're from a browser. `pbp/client.py` sends the headers and uses the TLS settings that
  currently get through. If NBA.com changes its filter, those need updating. The
  "Getting through the NBA's bot filter" section of `CLAUDE.md` explains what's required.
- **SSL certificate errors behind a corporate proxy:** point `SSL_CERT_FILE` and
  `REQUESTS_CA_BUNDLE` at your organization's CA bundle.
- **`no 2025-26 games for XYZ`:** check the team abbreviation against the list in the error
  message.
- **A game shows as `missing`:** the game doesn't exist or wasn't played, for example game 6 of
  a series that ended in five.
- **A game shows as `in_progress`:** the game hasn't finished, so it wasn't saved. Run the
  command again after the game ends.

## Project layout

```text
pbp/
  client.py    HTTP session that gets past NBA.com's bot filter, plus retries
  sources.py   data sources, game IDs, reading responses, finished-game check
  cache.py     where downloads are saved, and how to read them back
  fetch.py     the python -m pbp.fetch command
tests/         tests that run offline against saved real responses
CLAUDE.md      detailed notes on the data sources, conventions and plans
```

## Planned: calculations

The next stages will turn the saved play-by-play into clean per-game tables. After that come
calculation scripts that answer questions such as:

- How often does player X make a shot when teammate Y passes to them?
- How often does an opponent miss when player X is defending nearby?
- Which combination of teammates has the best plus-minus?

Some of these need NBA.com's player-tracking stats as well as play-by-play. `CLAUDE.md` lists
which data answers each one.

## Notes

The NBA.com endpoints used here are public but undocumented, and they can change without notice.
The data belongs to the NBA; check NBA.com's terms of use before redistributing it.

## License

MIT. See [LICENSE](LICENSE).
