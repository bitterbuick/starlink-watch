
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

# Add scripts directory to path to import starlink_utils
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from starlink_utils import FetchError, http_get


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """Replays a scripted sequence of responses/exceptions, recording each call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestHttpGet(unittest.TestCase):
    def test_returns_first_success_without_retrying(self):
        session = FakeSession([FakeResponse(200, "ok")])
        with mock.patch("starlink_utils.time.sleep") as sleep:
            resp = http_get("https://example.com", session=session)
        self.assertEqual(resp.text, "ok")
        self.assertEqual(len(session.calls), 1)
        sleep.assert_not_called()

    def test_always_sends_a_timeout(self):
        session = FakeSession([FakeResponse(200, "ok")])
        http_get("https://example.com", session=session)
        _url, kwargs = session.calls[0]
        self.assertIsNotNone(kwargs.get("timeout"))

    def test_retries_timeout_then_succeeds(self):
        session = FakeSession([
            requests.exceptions.ConnectTimeout("timed out"),
            requests.exceptions.ConnectTimeout("timed out"),
            FakeResponse(200, "recovered"),
        ])
        with mock.patch("starlink_utils.time.sleep") as sleep:
            resp = http_get("https://example.com", session=session)
        self.assertEqual(resp.text, "recovered")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_retries_5xx_and_gives_up_with_fetch_error(self):
        session = FakeSession([FakeResponse(503) for _ in range(4)])
        with mock.patch("starlink_utils.time.sleep"):
            with self.assertRaises(FetchError):
                http_get("https://example.com", session=session, attempts=4)
        self.assertEqual(len(session.calls), 4)

    def test_does_not_retry_client_error(self):
        session = FakeSession([FakeResponse(404)])
        with mock.patch("starlink_utils.time.sleep") as sleep:
            with self.assertRaises(FetchError):
                http_get("https://example.com", session=session)
        self.assertEqual(len(session.calls), 1)
        sleep.assert_not_called()

    def test_retries_429(self):
        session = FakeSession([FakeResponse(429), FakeResponse(200, "ok")])
        with mock.patch("starlink_utils.time.sleep"):
            resp = http_get("https://example.com", session=session)
        self.assertEqual(resp.text, "ok")
        self.assertEqual(len(session.calls), 2)


if __name__ == "__main__":
    unittest.main()
