"""Test helpers: fixture loading and a fake HTTP session, so no test touches the network.

The files in tests/fixtures/ are real responses saved on 2026-09-24, with the play-by-play
trimmed to its first and last few events.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> dict:
    return json.loads(fixture_bytes(name))


class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"", url: str = "https://example.test/"):
        self.status_code = status_code
        self.content = content
        self.url = url

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error for {self.url}", response=self)


class FakeSession:
    """Returns (or raises) the queued responses in order, and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        response.url = url
        return response


def ok(name: str) -> FakeResponse:
    """A 200 response whose body is the named fixture."""
    return FakeResponse(200, fixture_bytes(name))


class Sleeper:
    """A stand-in for time.sleep that records the waits instead of sleeping."""

    def __init__(self):
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
