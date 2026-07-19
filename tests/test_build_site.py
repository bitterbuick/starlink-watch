import json
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

import build_site


class TestBuildSite(unittest.TestCase):
    def test_load_series_dedupes_and_sorts(self):
        series = build_site.load_series("active_count")
        dates = [p["date"] for p in series]
        self.assertEqual(dates, sorted(set(dates)))

    def test_delta_30d(self):
        series = [
            {"date": "2026-01-01", "value": 100},
            {"date": "2026-01-15", "value": 110},
            {"date": "2026-02-05", "value": 130},
        ]
        self.assertEqual(build_site.delta_30d(series), 30)
        self.assertIsNone(build_site.delta_30d(series[:1]))

    def test_build_produces_page_with_embedded_data(self):
        build_site.build()
        page = (build_site.SITE / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="sw-data"', page)

        m = page.split('<script id="sw-data" type="application/json">', 1)[1]
        payload = json.loads(m.split("</script>", 1)[0])
        for spec in build_site.CHART_SPECS:
            self.assertIn(spec["key"], payload["series"])
            self.assertIn(spec["key"], payload["charts"])

        # interactive charts replaced the static PNGs
        self.assertNotIn("assets/active.png", page)
        self.assertIn('class="chart" data-key="active_count"', page)


if __name__ == "__main__":
    unittest.main()
