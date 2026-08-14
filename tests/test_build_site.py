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


class TestComparisonSection(unittest.TestCase):
    """The Starlink-vs-catalogue panels render from data/space_totals.json."""

    def sample_totals(self):
        this_year = build_site.datetime.date.today().year
        years = [
            {"year": this_year - 2, "starlink_kg": 50_000.0, "other_kg": 100_000.0,
             "starlink_alumina_kg": 66_150.0, "other_alumina_kg": 94_500.0},
            {"year": this_year - 1, "starlink_kg": 90_000.0, "other_kg": 110_000.0,
             "starlink_alumina_kg": 119_070.0, "other_alumina_kg": 103_950.0},
            {"year": this_year, "starlink_kg": 40_000.0, "other_kg": 60_000.0,
             "starlink_alumina_kg": 52_920.0, "other_alumina_kg": 56_700.0},
        ]
        return {
            "on_orbit": {"total_kg": 11_000_000.0, "starlink_kg": 3_000_000.0,
                         "other_kg": 8_000_000.0, "starlink_share": 0.2727,
                         "starlink_objects": 8000, "other_objects": 21000},
            "reentry_by_year": years,
            "chart_from_year": this_year - 5,
            "latest_complete_year": this_year - 1,
            "latest_year_delta": {
                "alumina_kg_with_starlink": 223_020.0,
                "alumina_kg_without_starlink": 103_950.0,
                "alumina_delta_kg": 119_070.0,
                "starlink_share_of_alumina": 0.5339,
            },
            "cumulative_alumina": {"with_starlink_kg": 493_290.0,
                                   "without_starlink_kg": 255_150.0,
                                   "delta_kg": 238_140.0, "starlink_share": 0.4827},
        }

    def test_renders_nothing_without_data(self):
        self.assertEqual(build_site.render_comparison({}), "")
        self.assertEqual(build_site.render_comparison({"reentry_by_year": []}), "")

    def test_renders_tiles_charts_and_the_delta(self):
        html = build_site.render_comparison(self.sample_totals())
        self.assertIn("Starlink vs Everything Else in Orbit", html)
        self.assertIn("cmp-chart", html)
        self.assertIn("Starlink share of on-orbit mass", html)
        # both series are named, so identity is never carried by color alone
        self.assertIn(">Starlink</span>", html)
        self.assertIn("All other catalogued objects", html)
        # the headline delta, in tonnes
        self.assertIn("119.1 t", html)

    def test_honors_chart_from_year(self):
        totals = self.sample_totals()
        totals["chart_from_year"] = build_site.datetime.date.today().year
        html = build_site.render_comparison(totals)
        self.assertIn(str(build_site.datetime.date.today().year), html)
        self.assertNotIn(f'>{build_site.datetime.date.today().year - 2}</text>', html)

    def test_current_year_bars_are_marked_partial(self):
        html = build_site.render_comparison(self.sample_totals())
        self.assertIn("year to date", html)
        self.assertIn('opacity="0.55"', html)

    def test_stacked_bars_handle_an_empty_year_list(self):
        self.assertIn("No catalogue comparison yet.",
                      build_site.render_stacked_bars([], build_site.COMPARISON_CHARTS[0]))


if __name__ == "__main__":
    unittest.main()
