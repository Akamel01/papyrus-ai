import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.append(r"c:\gpt\SME")

from tools.gold_standard_bench.refiner import CodeRefiner

class MockLLM:
    def generate(self, *args, **kwargs):
        return "Mock Response"

class TestRefinerLogic(unittest.TestCase):
    def setUp(self):
        self.refiner = CodeRefiner(MockLLM(), r"c:\gpt\SME")

    def test_identify_config_target(self):
        # Test mapping for depth presets
        target = self.refiner.identify_target_file("Insufficient paper count in response")
        self.assertEqual(target, "src/config/depth_presets.py")
        
        target = self.refiner.identify_target_file("Depth level is too shallow")
        self.assertEqual(target, "src/config/depth_presets.py")

        # Test mapping for thresholds
        target = self.refiner.identify_target_file("Confidence level below threshold")
        self.assertEqual(target, "src/config/thresholds.py")
        
    def test_identify_logic_target(self):
        # Test mapping for personas
        target = self.refiner.identify_target_file("No methodology section found")
        self.assertEqual(target, "src/academic_v2/librarian.py")
        
        target = self.refiner.identify_target_file("Weak analysis and depth")
        self.assertEqual(target, "src/academic_v2/drafter.py")

if __name__ == '__main__':
    unittest.main()
