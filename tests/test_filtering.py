
import unittest
import sys
import os
from pathlib import Path

# Add scripts directory to path to import starlink_utils
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from starlink_utils import looks_starlink_critical

class TestStarlinkFiltering(unittest.TestCase):
    def test_positive_cases(self):
        cases = [
            ("Starlink outage hits Europe", "Users reported downtime.", "http://example.com"),
            ("Starshield vulnerabilities exposed", "Hackers claim access.", "http://example.com"),
            ("SpaceX Starlink debris concerns", "ESA worried about reentry.", "http://example.com"),
             ("Astronomers complain about Starlink brightness", "Telescopes affected.", "http://example.com"),
        ]
        for title, summary, link in cases:
            with self.subTest(title=title):
                self.assertTrue(looks_starlink_critical(title, summary, link))

    def test_negative_cases(self):
        cases = [
            ("Starship launch successful", "Spacex launches heavy rocket.", "http://example.com"),
            ("Starlink expands to new country", "Service now available in Antarctica.", "http://example.com"), # Marketing/Expansion
            ("Blue Origin announces new rocket", "Jeff Bezos reveals plans.", "http://example.com"),
            ("SpaceX Falcon 9 launches crew", "Astronauts go to ISS.", "http://example.com"),
        ]
        for title, summary, link in cases:
            with self.subTest(title=title):
                self.assertFalse(looks_starlink_critical(title, summary, link))

    def test_mixed_cases(self):
        # Mentioning starlink but also negative keywords that might disqualify if logic was strict? 
        # But mostly we want to avoid False Negatives on valid criticisms.
        # The current logic is: Must have POS, Must NOT have NEG, Must have CRITICISM.
        
        # Test: Starlink on a Starship flight? (If Starship is in NEG, it might filter it out even if relevant)
        # "Starship launches Starlink satellites, causes debris" -> POS=True, NEG=True (Starship), CRITICISM=True.
        # However, the NEG regex for Starship is `\bstarship\b(?!.*\bstarlink\b)`.
        # Since "starlink" FOLLOWS "starship", the NEG regex does NOT match. 
        # So it falls through to CRITICISM. Debris is in CRITICISM. So it should be True.
        
        # Original test case was: ("Starship launches Starlink", "Debris everywhere", "")
        # This SHOULD be True.
        self.assertTrue(looks_starlink_critical("Starship launches Starlink", "Debris everywhere", ""))

        # Test: Starship launch WITHOUT criticism
        self.assertFalse(looks_starlink_critical("Starship launches Starlink", "Successful mission", ""))

if __name__ == "__main__":
    unittest.main()
