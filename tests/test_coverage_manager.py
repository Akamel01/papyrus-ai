import unittest
import shutil
import logging
from pathlib import Path
from src.acquisition.coverage_manager import CoverageManager

logging.basicConfig(level=logging.ERROR)

class TestCoverageManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/temp_data")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.cm = CoverageManager(str(self.test_dir / "test_coverage.json"))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_signature_generation(self):
        sig1 = self.cm.generate_signature("OpenAlex", "Bayesian", {"type": ["article"]})
        sig2 = self.cm.generate_signature("openalex ", " bayesian ", {"type": ["ARTICLE"]})
        self.assertEqual(sig1, sig2, "Signatures should be case/space insensitive")

        sig3 = self.cm.generate_signature("OpenAlex", "Other", {"type": ["article"]})
        self.assertNotEqual(sig1, sig3, "Different keyword should have different signature")

    def test_gap_calculation_fresh(self):
        """Test Case 1: Fresh Run"""
        sig = "sig1"
        target = (2000, 2024)
        gaps = self.cm.calculate_gaps(sig, target)
        self.assertEqual(gaps, [(2000, 2024)], "Should return full target interval for empty state")

    def test_gap_calculation_expansion(self):
        """Test Case 2: Expansion (1990-2024) when we have (2000-2024)"""
        sig = "sig2"
        self.cm.mark_covered(sig, (2000, 2024))
        
        target = (1990, 2024)
        gaps = self.cm.calculate_gaps(sig, target)
        self.assertEqual(gaps, [(1990, 1999)], "Should only fetch the historical gap")

    def test_gap_calculation_maintenance(self):
        """Test Case 3: Maintenance (2000-2024) when we have (2000-2023)"""
        sig = "sig3"
        self.cm.mark_covered(sig, (2000, 2023))
        
        target = (2000, 2024)
        gaps = self.cm.calculate_gaps(sig, target)
        self.assertEqual(gaps, [(2024, 2024)], "Should fetch the new year")

    def test_gap_calculation_contraction(self):
        """Test Case 4: Contraction (2010-2020) when we have (2000-2024)"""
        sig = "sig4"
        self.cm.mark_covered(sig, (2000, 2024))
        
        target = (2010, 2020)
        gaps = self.cm.calculate_gaps(sig, target)
        self.assertEqual(gaps, [], "Should return no gaps")

    def test_fragmented_coverage(self):
        """Test Case 5: Fragmented Coverage"""
        sig = "sig5"
        # We have [2000-2005] and [2010-2015]
        self.cm.mark_covered(sig, (2000, 2005))
        self.cm.mark_covered(sig, (2010, 2015))
        
        target = (2000, 2020)
        # Expect gaps: [2006-2009] and [2016-2020]
        gaps = self.cm.calculate_gaps(sig, target)
        self.assertEqual(gaps, [(2006, 2009), (2016, 2020)], "Should find multiple disjoint gaps")

    def test_merging_logic(self):
        sig = "sig_merge"
        self.cm.mark_covered(sig, (2000, 2005))
        self.cm.mark_covered(sig, (2006, 2010))
        
        # Should merge to [2000, 2010]
        intervals = self.cm.coverage_map[sig]
        self.assertEqual(intervals, [(2000, 2010)], "Should merge adjacent intervals")
        
        self.cm.mark_covered(sig, (2005, 2015))
        # Should merge overlapping [2000, 2010] + [2005, 2015] -> [2000, 2015]
        intervals = self.cm.coverage_map[sig]
        self.assertEqual(intervals, [(2000, 2015)], "Should merge overlapping intervals")

if __name__ == '__main__':
    unittest.main()
