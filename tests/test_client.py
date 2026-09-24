import pytest
import requests

from fakes import FakeResponse, FakeSession, Sleeper
from pbp import client


def test_session_sends_browser_headers_and_uses_standard_tls():
    session = client.make_session()
    assert session.headers["Referer"] == "https://www.nba.com/"
    assert session.headers["Sec-Fetch-Mode"] == "cors"
    assert isinstance(session.get_adapter("https://cdn.nba.com/"), client.StandardTLSAdapter)


def test_retries_timeouts_with_exponential_backoff():
    session = FakeSession(requests.Timeout(), requests.ConnectionError(), FakeResponse(200))
    sleep = Sleeper()
    response = client.get_with_retries(session, "https://x.test/", sleep=sleep)
    assert response.status_code == 200
    assert sleep.waits == [2.0, 4.0]


def test_retries_server_errors_and_rate_limits():
    session = FakeSession(FakeResponse(503), FakeResponse(429), FakeResponse(200))
    assert client.get_with_retries(session, "https://x.test/", sleep=Sleeper()).status_code == 200
    assert len(session.calls) == 3


@pytest.mark.parametrize("status", [403, 404])
def test_does_not_retry_client_errors(status):
    session = FakeSession(FakeResponse(status))
    assert client.get_with_retries(session, "https://x.test/", sleep=Sleeper()).status_code == status
    assert len(session.calls) == 1


def test_gives_up_after_the_last_retry():
    session = FakeSession(*[requests.Timeout()] * 4)
    with pytest.raises(requests.Timeout):
        client.get_with_retries(session, "https://x.test/", retries=3, sleep=Sleeper())
    assert len(session.calls) == 4

    session = FakeSession(*[FakeResponse(503)] * 2)
    assert client.get_with_retries(session, "https://x.test/", retries=1, sleep=Sleeper()).status_code == 503
