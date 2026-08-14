
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add scripts directory to path
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

import compute_space_totals as totals
from starlink_utils import FetchError

HEADER = ["OBJECT_NAME", "OBJECT_ID", "NORAD_CAT_ID", "OBJECT_TYPE", "OPS_STATUS_CODE",
          "OWNER", "LAUNCH_DATE", "LAUNCH_SITE", "DECAY_DATE", "PERIOD", "INCLINATION",
          "APOGEE", "PERIGEE", "RCS", "DATA_STATUS_CODE", "ORBIT_CENTER", "ORBIT_TYPE"]


def row(name, otype, decay="", rcs=""):
    values = dict.fromkeys(HEADER, "")
    values.update({"OBJECT_NAME": name, "OBJECT_TYPE": otype,
                   "DECAY_DATE": decay, "RCS": rcs})
    return values


def as_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADER)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def parsed(rows):
    return list(csv.DictReader(io.StringIO(as_csv(rows))))


class TestMassModel(unittest.TestCase):
    def test_rcs_drives_the_estimate(self):
        small = totals.estimate_mass_kg("DEB", 0.01)
        large = totals.estimate_mass_kg("DEB", 1.0)
        self.assertLess(small, large)

    def test_missing_rcs_falls_back_to_type_default(self):
        self.assertEqual(totals.estimate_mass_kg("R/B", None),
                         float(totals.TOTALS_CFG["default_mass_kg"]["R/B"]))
        self.assertEqual(totals.estimate_mass_kg("R/B", 0),
                         float(totals.TOTALS_CFG["default_mass_kg"]["R/B"]))

    def test_estimate_is_clamped_to_type_bounds(self):
        lo, hi = totals.TOTALS_CFG["mass_bounds_kg"]["DEB"]
        self.assertLessEqual(totals.estimate_mass_kg("DEB", 10_000), float(hi))
        self.assertGreaterEqual(totals.estimate_mass_kg("DEB", 1e-9), float(lo))

    def test_unknown_object_type_is_treated_as_unk(self):
        self.assertEqual(totals.object_type("R/B"), "R/B")
        self.assertEqual(totals.object_type("TBA"), "UNK")
        self.assertEqual(totals.object_type(None), "UNK")

    def test_parse_year_tolerates_partial_and_junk_dates(self):
        self.assertEqual(totals.parse_year("2024-03-11"), 2024)
        self.assertEqual(totals.parse_year("2024"), 2024)
        self.assertIsNone(totals.parse_year(""))
        self.assertIsNone(totals.parse_year("n/a"))
        self.assertIsNone(totals.parse_year("1855-01-01"))


class TestSummaries(unittest.TestCase):
    def setUp(self):
        self.rows = parsed([
            row("STARLINK-1234", "PAY"),                       # on orbit
            row("STARLINK-1235", "PAY"),                       # on orbit
            row("STARLINK-1000", "PAY", decay="2024-05-02"),   # re-entered
            row("STARLINK-1001", "PAY", decay="2025-01-09"),
            row("COSMOS 2251 DEB", "DEB", rcs="0.02"),         # on orbit
            row("FALCON 9 R/B", "R/B", decay="2024-11-30", rcs="12.5"),
            row("SL-8 R/B", "R/B", decay="2025-02-02", rcs="8.0"),
            row("UNKNOWN OBJECT", "TBA", decay="2025-06-01"),
        ])
        self.totals = totals.build_totals(self.rows)

    def test_splits_on_orbit_mass_between_starlink_and_everything_else(self):
        on_orbit = self.totals["on_orbit"]
        self.assertEqual(on_orbit["starlink_objects"], 2)
        self.assertEqual(on_orbit["other_objects"], 1)
        self.assertAlmostEqual(
            on_orbit["total_kg"], on_orbit["starlink_kg"] + on_orbit["other_kg"], places=1)
        self.assertGreater(on_orbit["starlink_share"], 0)
        self.assertLess(on_orbit["starlink_share"], 1)

    def test_reentries_are_bucketed_by_year(self):
        by_year = {y["year"]: y for y in self.totals["reentry_by_year"]}
        self.assertEqual(sorted(by_year), [2024, 2025])
        self.assertEqual(by_year[2024]["starlink_n"], 1)
        self.assertEqual(by_year[2024]["other_n"], 1)   # Falcon 9 upper stage
        self.assertEqual(by_year[2025]["other_n"], 2)   # SL-8 stage + unknown object

    def test_rocket_bodies_count_as_other_not_starlink(self):
        by_year = {y["year"]: y for y in self.totals["reentry_by_year"]}
        self.assertGreater(by_year[2024]["other_kg"], 0)

    def test_cumulative_alumina_delta_is_the_starlink_contribution(self):
        cum = self.totals["cumulative_alumina"]
        self.assertAlmostEqual(
            cum["with_starlink_kg"] - cum["without_starlink_kg"], cum["delta_kg"], places=1)
        self.assertGreater(cum["delta_kg"], 0)
        self.assertAlmostEqual(
            cum["with_starlink_kg"],
            sum(y["starlink_alumina_kg"] + y["other_alumina_kg"]
                for y in self.totals["reentry_by_year"]),
            places=1)

    def test_headline_delta_uses_the_last_complete_year(self):
        delta = self.totals["latest_year_delta"]
        self.assertLess(self.totals["latest_complete_year"],
                        totals.datetime.date.today().year)
        self.assertAlmostEqual(
            delta["alumina_kg_with_starlink"] - delta["alumina_kg_without_starlink"],
            delta["alumina_delta_kg"], places=1)

    def test_alumina_never_exceeds_reentered_mass_times_yield(self):
        for year in self.totals["reentry_by_year"]:
            mass = year["starlink_kg"] + year["other_kg"]
            alumina = year["starlink_alumina_kg"] + year["other_alumina_kg"]
            self.assertLessEqual(alumina, mass * totals.ALUMINA_YIELD + 1e-6)


class TestCatalogFetch(unittest.TestCase):
    def test_rejects_a_catalogue_missing_expected_columns(self):
        class Resp:
            text = "FOO,BAR\n1,2\n"
        with mock.patch.object(totals, "http_get", return_value=Resp()):
            with self.assertRaises(totals.CatalogError):
                totals.fetch_catalog()

    def test_keeps_previous_output_when_satcat_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            previous = {"catalog_objects": 42}
            (data / "space_totals.json").write_text(json.dumps(previous), encoding="utf-8")
            with mock.patch.object(totals, "DATA", data), \
                 mock.patch.object(totals, "fetch_catalog", side_effect=FetchError("boom")):
                self.assertEqual(totals.main(), 0)
            self.assertEqual(json.loads((data / "space_totals.json").read_text()), previous)

    def test_fails_when_there_is_nothing_to_fall_back_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(totals, "DATA", Path(tmp)), \
                 mock.patch.object(totals, "fetch_catalog", side_effect=FetchError("boom")):
                self.assertEqual(totals.main(), 1)


if __name__ == "__main__":
    unittest.main()
