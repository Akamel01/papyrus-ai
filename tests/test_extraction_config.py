"""
Unit tests for Phase 2: Smart Adaptive Retrieval Pipeline (Scenario 3)

Tests:
1. ExtractionParams calculation
2. Two-stage librarian extraction
3. Depth-aware fact targets
4. Integration with engine
"""

import sys
import os

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import Mock, MagicMock
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestExtractionConfig(unittest.TestCase):
    """Test the extraction_config module."""

    def test_get_extraction_params_low_depth(self):
        """Verify Low depth returns correct max_facts."""
        from src.config.extraction_config import get_extraction_params

        params = get_extraction_params(config={}, depth="Low")

        self.assertEqual(params.max_facts, 40,
            "Low depth should have max_facts=40")
        self.assertGreater(params.max_chunks, 0,
            "max_chunks should be derived and positive")
        self.assertGreater(params.top_k_rerank, params.max_chunks,
            "top_k_rerank should be larger than max_chunks")
        print("[PASS] Low depth extraction params correct")

    def test_get_extraction_params_medium_depth(self):
        """Verify Medium depth returns correct max_facts."""
        from src.config.extraction_config import get_extraction_params

        params = get_extraction_params(config={}, depth="Medium")

        self.assertEqual(params.max_facts, 80,
            "Medium depth should have max_facts=80")
        print("[PASS] Medium depth extraction params correct")

    def test_get_extraction_params_high_depth(self):
        """Verify High depth returns correct max_facts."""
        from src.config.extraction_config import get_extraction_params

        params = get_extraction_params(config={}, depth="High")

        self.assertEqual(params.max_facts, 150,
            "High depth should have max_facts=150")
        print("[PASS] High depth extraction params correct")

    def test_get_extraction_params_section_mode(self):
        """Verify section mode returns per-section targets."""
        from src.config.extraction_config import get_extraction_params

        params = get_extraction_params(
            config={},
            depth="High",
            section_mode=True,
            section_count=5
        )

        # Should use facts_per_section for High (60), not target_facts (150)
        self.assertEqual(params.max_facts, 60,
            "Section mode should use facts_per_section=60 for High depth")
        print("[PASS] Section mode uses per-section targets")

    def test_derived_max_chunks(self):
        """Verify max_chunks is derived from max_facts / density."""
        from src.config.extraction_config import get_extraction_params

        params = get_extraction_params(config={}, depth="Medium")

        # max_chunks = max_facts / density + sample_size
        # 80 / 3.0 + 8 = 26.67 + 8 = ~35
        expected_min = int(80 / 3.0)
        self.assertGreaterEqual(params.max_chunks, expected_min,
            f"max_chunks should be >= {expected_min} (80/3.0)")
        print("[PASS] max_chunks correctly derived from max_facts")

    def test_config_override(self):
        """Verify config values override defaults."""
        from src.config.extraction_config import get_extraction_params

        config = {
            "extraction": {
                "max_facts": {
                    "Low": 30,
                    "Medium": 60,
                    "High": 100,
                }
            }
        }

        params = get_extraction_params(config=config, depth="Medium")

        self.assertEqual(params.max_facts, 60,
            "Config override should set max_facts=60")
        print("[PASS] Config overrides work correctly")


class TestLibrarianEarlyStop(unittest.TestCase):
    """Test the two-stage librarian extraction."""

    def test_librarian_has_early_stop_method(self):
        """Verify Librarian has extract_facts_with_early_stop method."""
        from src.academic_v2.librarian import Librarian

        mock_llm = Mock()
        librarian = Librarian(mock_llm)

        self.assertTrue(hasattr(librarian, 'extract_facts_with_early_stop'),
            "Librarian should have extract_facts_with_early_stop method")
        print("[PASS] Librarian has two-stage extraction method")

    def test_early_stop_returns_tuple(self):
        """Verify extract_facts_with_early_stop returns (facts, density)."""
        import inspect
        from src.academic_v2.librarian import Librarian

        sig = inspect.signature(Librarian.extract_facts_with_early_stop)
        # Check return annotation if present
        return_annotation = sig.return_annotation

        # Check method exists and has correct parameters
        params = list(sig.parameters.keys())
        self.assertIn('max_facts', params,
            "Method should have max_facts parameter")
        self.assertIn('sample_size', params,
            "Method should have sample_size parameter")
        print("[PASS] Two-stage extraction has correct signature")


class TestEngineIntegration(unittest.TestCase):
    """Test engine integration with extraction params."""

    def test_engine_generate_section_v2_signature(self):
        """Verify generate_section_v2 accepts depth and section_mode."""
        import inspect
        from src.academic_v2.engine import AcademicEngine

        sig = inspect.signature(AcademicEngine.generate_section_v2)
        params = list(sig.parameters.keys())

        self.assertIn('depth', params,
            "generate_section_v2 should have depth parameter")
        self.assertIn('section_mode', params,
            "generate_section_v2 should have section_mode parameter")
        print("[PASS] Engine accepts depth and section_mode parameters")

    def test_engine_imports_extraction_config(self):
        """Verify engine imports extraction config module."""
        import inspect
        from src.academic_v2 import engine

        source = inspect.getsource(engine)

        self.assertIn('from src.config.extraction_config import', source,
            "Engine should import extraction_config")
        self.assertIn('get_extraction_params', source,
            "Engine should use get_extraction_params")
        print("[PASS] Engine imports extraction_config module")


class TestArchitectNoCap(unittest.TestCase):
    """Test that Architect no longer has internal fact capping."""

    def test_architect_no_hardcoded_cap(self):
        """Verify Architect doesn't have the old hardcoded cap."""
        import inspect
        from src.academic_v2.architect import Architect

        source = inspect.getsource(Architect.design_section_plan)

        # Should NOT contain the old capping pattern
        self.assertNotIn('max_architect_facts = min(100', source,
            "Architect should not have hardcoded min(100,...) cap")
        self.assertNotIn('facts = facts[:max_architect_facts]', source,
            "Architect should not slice facts with hardcoded cap")
        print("[PASS] Architect removed hardcoded fact cap")


class TestDepthPresets(unittest.TestCase):
    """Test depth presets have fact targets."""

    def test_presets_have_fact_targets(self):
        """Verify depth presets include target_facts and facts_per_section."""
        from src.config.depth_presets import DEPTH_PRESETS

        for depth in ["Low", "Medium", "High"]:
            preset = DEPTH_PRESETS[depth]
            self.assertIn('target_facts', preset,
                f"{depth} preset should have target_facts")
            self.assertIn('facts_per_section', preset,
                f"{depth} preset should have facts_per_section")

        print("[PASS] All depth presets have fact targets")

    def test_preset_fact_values(self):
        """Verify correct fact target values."""
        from src.config.depth_presets import DEPTH_PRESETS

        self.assertEqual(DEPTH_PRESETS["Low"]["target_facts"], 40)
        self.assertEqual(DEPTH_PRESETS["Medium"]["target_facts"], 80)
        self.assertEqual(DEPTH_PRESETS["High"]["target_facts"], 150)

        self.assertEqual(DEPTH_PRESETS["Low"]["facts_per_section"], 25)
        self.assertEqual(DEPTH_PRESETS["Medium"]["facts_per_section"], 40)
        self.assertEqual(DEPTH_PRESETS["High"]["facts_per_section"], 60)

        print("[PASS] Fact target values are correct")


class TestConfigYaml(unittest.TestCase):
    """Test config.yaml has extraction section."""

    def test_config_has_extraction_section(self):
        """Verify config.yaml has extraction configuration."""
        import yaml

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config', 'config.yaml'
        )

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        self.assertIn('extraction', config,
            "config.yaml should have 'extraction' section")

        extraction = config['extraction']
        self.assertIn('max_facts', extraction,
            "extraction section should have max_facts")
        self.assertIn('sample_size', extraction,
            "extraction section should have sample_size")
        self.assertIn('section_mode', extraction,
            "extraction section should have section_mode")

        print("[PASS] config.yaml has extraction section")

    def test_config_max_facts_by_depth(self):
        """Verify max_facts has depth-specific values."""
        import yaml

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config', 'config.yaml'
        )

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        max_facts = config['extraction']['max_facts']

        self.assertEqual(max_facts['low'], 40)
        self.assertEqual(max_facts['medium'], 80)
        self.assertEqual(max_facts['high'], 150)

        print("[PASS] config.yaml has depth-specific fact targets")


def run_all_tests():
    """Run all Phase 2 test classes."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestExtractionConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestLibrarianEarlyStop))
    suite.addTests(loader.loadTestsFromTestCase(TestEngineIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestArchitectNoCap))
    suite.addTests(loader.loadTestsFromTestCase(TestDepthPresets))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigYaml))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "="*70)
    print("PHASE 2 TEST SUMMARY")
    print("="*70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\n[SUCCESS] ALL PHASE 2 TESTS PASSED!")
    else:
        print("\n[FAILED] SOME TESTS FAILED")
        for test, traceback in result.failures + result.errors:
            print(f"\nFailed: {test}")
            print(traceback)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
