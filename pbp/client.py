"""HTTP access to NBA.com endpoints.

cdn.nba.com and stats.nba.com sit behind Akamai's bot filter. A request only gets through with
nearly the full set of Chrome headers AND Python's standard TLS settings; Akamai rejects
urllib3's own TLS settings even when the headers are right. See "Getting through the NBA's bot
filter" in CLAUDE.md.
"""

from __future__ import annotations

import ssl
import time
from typing import Callable

import requests
from requests.adapters import HTTPAdapter

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "Sec-Ch-Ua": '"Chromium";v="140", "Google Chrome";v="140", "Not;A=Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

DEFAULT_TIMEOUT = 20  # seconds
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class StandardTLSAdapter(HTTPAdapter):
    """An adapter that uses ssl.create_default_context() instead of urllib3's TLS settings."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().proxy_manager_for(*args, **kwargs)


def make_session() -> requests.Session:
    """Return a session that gets through the NBA.com bot filter."""
    session = requests.Session()
    session.mount("https://", StandardTLSAdapter())
    session.headers.update(BROWSER_HEADERS)
    return session


def get_with_retries(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    retries: int = 3,
    backoff: float = 2.0,
    timeout: float = DEFAULT_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """GET a URL, retrying timeouts, connection errors and 429/5xx responses.

    Waits backoff, 2*backoff, 4*backoff, ... seconds between attempts. Any other response,
    including 403 and 404, is returned for the caller to interpret. After the last attempt, a
    retryable response is returned and a timeout or connection error is raised.
    """
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == retries:
                raise
        else:
            if response.status_code not in RETRY_STATUSES or attempt == retries:
                return response
        sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")
