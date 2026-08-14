
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add scripts directory to path to import the metrics script
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

import compute_starlink_metrics as metrics
from starlink_utils import FetchError


class TestMetricsResilience(unittest.TestCase):
    """A transient CelesTrak outage should degrade, not fail the scheduled run."""

    def test_keeps_previous_snapshot_when_active_count_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            previous = {"active_count": 8123, "generated_at": "2026-01-01T00:00:00Z"}
            (data / "metrics.json").write_text(json.dumps(previous), encoding="utf-8")

            with mock.patch.object(metrics, "DATA", data), \
                 mock.patch.object(metrics, "fetch_starlink_active_count",
                                   side_effect=FetchError("boom")):
                self.assertEqual(metrics.main(), 0)

            # Untouched: the site keeps publishing the last good numbers.
            self.assertEqual(json.loads((data / "metrics.json").read_text()), previous)

    def test_fails_when_no_previous_snapshot_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(metrics, "DATA", Path(tmp)), \
                 mock.patch.object(metrics, "fetch_starlink_active_count",
                                   side_effect=FetchError("boom")):
                self.assertEqual(metrics.main(), 1)

    def test_decayed_total_falls_back_to_stored_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            stored = ["STARLINK-1000", "STARLINK-1001", "STARLINK-1002"]
            (state / "decayed_starlinks.json").write_text(json.dumps(stored), encoding="utf-8")

            with mock.patch.object(metrics, "STATE", state), \
                 mock.patch.object(metrics, "http_get", side_effect=FetchError("boom")):
                self.assertEqual(metrics.fetch_recent_decayed_starlink(), len(stored))

            # The cumulative store is left intact for the next run.
            self.assertEqual(
                json.loads((state / "decayed_starlinks.json").read_text()), stored
            )

    def test_decayed_total_survives_corrupt_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "decayed_starlinks.json").write_text("{not json", encoding="utf-8")

            with mock.patch.object(metrics, "STATE", state), \
                 mock.patch.object(metrics, "http_get", side_effect=FetchError("boom")):
                self.assertEqual(metrics.fetch_recent_decayed_starlink(), 0)


if __name__ == "__main__":
    unittest.main()
