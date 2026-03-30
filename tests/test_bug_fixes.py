"""
Unit tests for the 4 bug fixes:
1. Section restart fallback (sequential_rag.py)
2. HyDE knowledge_source parameter (hyde.py)
3. Proofreading instruction filter (proofreading.py)
4. Configurable librarian chunk limit (engine.py)
"""

import sys
import os

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import Mock, MagicMock, patch
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestFix1SectionRestartFallback(unittest.TestCase):
    """Test that section generation failures don't crash the generator."""

    def test_exception_not_reraised_in_section_loop(self):
        """Verify the raise statement was removed from sequential_rag.py."""
        import inspect
        from src.retrieval.sequential_rag import SequentialRAG

        # Get source code of the class
        source = inspect.getsource(SequentialRAG)

        # Check that the problematic pattern is NOT present
        # The old code had: except Exception as e:\n...raise e
        # We need to verify this pattern is gone in the section generation context

        # Find the _process_with_sections_core method
        lines = source.split('\n')
        in_except_block = False
        found_raise_e = False

        for i, line in enumerate(lines):
            if 'except Exception as e:' in line and 'V2 Generation' in ''.join(lines[max(0,i-5):i+5]):
                in_except_block = True
            if in_except_block and 'raise e' in line:
                found_raise_e = True
                break
            if in_except_block and (line.strip() and not line.strip().startswith('#') and
                                     'logger' not in line and 'raise e' not in line):
                in_except_block = False

        self.assertFalse(found_raise_e,
            "Found 'raise e' in V2 Generation exception handler - fix not applied correctly")
        print("[PASS] Fix 1 VERIFIED: 'raise e' removed from section generation exception handler")


class TestFix2HyDEKnowledgeSource(unittest.TestCase):
    """Test that HyDE handles knowledge_source parameter correctly."""

    def test_hyde_search_signature_has_knowledge_source(self):
        """Verify HyDE.search() accepts knowledge_source parameter."""
        import inspect
        from src.retrieval.hyde import HyDERetriever

        sig = inspect.signature(HyDERetriever.search)
        params = list(sig.parameters.keys())

        self.assertIn('knowledge_source', params,
            "knowledge_source parameter not found in HyDE.search() signature")

        # Check default value
        default = sig.parameters['knowledge_source'].default
        self.assertEqual(default, 'both',
            f"knowledge_source default should be 'both', got '{default}'")

        print("[PASS] Fix 2a VERIFIED: knowledge_source parameter added to HyDE.search()")

    def test_hyde_converts_knowledge_source_to_filters(self):
        """Verify HyDE converts knowledge_source to proper filter dict."""
        from src.retrieval.hyde import HyDERetriever

        # Create mock dependencies
        mock_llm = Mock()
        mock_embedder = Mock()
        mock_embedder.embed_query = Mock(return_value=[0.1] * 4096)
        mock_vector_store = Mock()
        mock_vector_store.search = Mock(return_value=[])

        hyde = HyDERetriever(mock_llm, mock_embedder, mock_vector_store)

        # Test shared_only
        hyde.search("test query", use_hyde=False, knowledge_source="shared_only")
        call_args = mock_vector_store.search.call_args
        filters = call_args.kwargs.get('filters', call_args[1].get('filters', {}))
        self.assertTrue(filters.get('user_id_is_null', False),
            "shared_only should set user_id_is_null=True in filters")
        print("[PASS] Fix 2b VERIFIED: shared_only sets user_id_is_null filter")

        # Test user_only with user_id
        mock_vector_store.search.reset_mock()
        hyde.search("test query", use_hyde=False, user_id="test_user", knowledge_source="user_only")
        call_args = mock_vector_store.search.call_args
        filters = call_args.kwargs.get('filters', call_args[1].get('filters', {}))
        self.assertEqual(filters.get('user_id'), 'test_user',
            "user_only should set user_id filter")
        print("[PASS] Fix 2c VERIFIED: user_only sets user_id filter")

        # Test both with user_id
        mock_vector_store.search.reset_mock()
        hyde.search("test query", use_hyde=False, user_id="test_user", knowledge_source="both")
        call_args = mock_vector_store.search.call_args
        filters = call_args.kwargs.get('filters', call_args[1].get('filters', {}))
        self.assertEqual(filters.get('user_id_or_null'), 'test_user',
            "both should set user_id_or_null filter")
        print("[PASS] Fix 2d VERIFIED: both sets user_id_or_null filter")

    def test_hyde_no_typeerror_with_knowledge_source(self):
        """Verify no TypeError when calling HyDE with knowledge_source."""
        from src.retrieval.hyde import HyDERetriever

        mock_llm = Mock()
        mock_embedder = Mock()
        mock_embedder.embed_query = Mock(return_value=[0.1] * 4096)
        mock_vector_store = Mock()
        mock_vector_store.search = Mock(return_value=[])

        hyde = HyDERetriever(mock_llm, mock_embedder, mock_vector_store)

        # This should NOT raise TypeError
        try:
            hyde.search("test", use_hyde=False, knowledge_source="user_only", user_id="test")
            print("[PASS] Fix 2e VERIFIED: No TypeError when calling with knowledge_source")
        except TypeError as e:
            self.fail(f"TypeError raised: {e}")


class TestFix3ProofreadingFilter(unittest.TestCase):
    """Test the improved instruction filter logic."""

    def setUp(self):
        """Create mock proofreader instance."""
        # The ProofreadingMixin is a mixin class, we need to create a minimal test class
        from src.retrieval.sequential.proofreading import ProofreadingMixin

        # Create a test class that uses the mixin
        class TestProofreader(ProofreadingMixin):
            def __init__(self, pipeline):
                self.pipeline = pipeline

        mock_pipeline = {
            "llm": Mock(),
            "config": {}
        }
        self.proofreader = TestProofreader(mock_pipeline)

    def test_filter_accepts_specific_instructions(self):
        """Verify filter accepts instructions with quoted targets."""
        # Instruction with quoted target should be accepted
        instruction = {"specific_action": "Clarify 'neural network architecture' by adding a definition"}
        result = self.proofreader._is_actionable_instruction(instruction)
        self.assertTrue(result,
            "Should accept instruction with quoted target")
        print("[PASS] Fix 3a VERIFIED: Accepts instructions with quoted targets")

    def test_filter_accepts_specific_verbs(self):
        """Verify filter accepts instructions with specific verbs."""
        instruction = {"specific_action": "Replace the vague term with 'convolutional layer'"}
        result = self.proofreader._is_actionable_instruction(instruction)
        self.assertTrue(result,
            "Should accept instruction with specific verb 'replace'")
        print("[PASS] Fix 3b VERIFIED: Accepts instructions with specific verbs")

    def test_filter_rejects_purely_vague(self):
        """Verify filter rejects purely vague instructions."""
        instruction = {"specific_action": "improve the clarity of this section"}
        result = self.proofreader._is_actionable_instruction(instruction)
        self.assertFalse(result,
            "Should reject purely vague instruction without target")
        print("[PASS] Fix 3c VERIFIED: Rejects purely vague instructions")

    def test_filter_rejects_short_instructions(self):
        """Verify filter rejects too-short instructions."""
        instruction = {"specific_action": "fix it"}
        result = self.proofreader._is_actionable_instruction(instruction)
        self.assertFalse(result,
            "Should reject instruction shorter than 10 chars")
        print("[PASS] Fix 3d VERIFIED: Rejects too-short instructions")

    def test_filter_rejects_entire_section(self):
        """Verify filter rejects instructions targeting entire section."""
        instruction = {"specific_action": "Rewrite the entire section to be more concise"}
        result = self.proofreader._is_actionable_instruction(instruction)
        self.assertFalse(result,
            "Should reject instruction targeting entire section")
        print("[PASS] Fix 3e VERIFIED: Rejects 'entire section' instructions")

    def test_filter_accepts_specific_rewrite(self):
        """Verify filter accepts rewrite with specific target."""
        instruction = {"specific_action": "Rewrite 'the data shows' to 'the experimental results demonstrate'"}
        result = self.proofreader._is_actionable_instruction(instruction)
        self.assertTrue(result,
            "Should accept specific rewrite with 'to' clause")
        print("[PASS] Fix 3f VERIFIED: Accepts specific rewrite instructions")


class TestFix4ConfigurableChunkLimit(unittest.TestCase):
    """Test that librarian chunk limit is configurable."""

    def test_engine_accepts_config_parameter(self):
        """Verify AcademicEngine constructor accepts config parameter."""
        import inspect
        from src.academic_v2.engine import AcademicEngine

        sig = inspect.signature(AcademicEngine.__init__)
        params = list(sig.parameters.keys())

        self.assertIn('config', params,
            "config parameter not found in AcademicEngine.__init__()")
        print("[PASS] Fix 4a VERIFIED: AcademicEngine accepts config parameter")

    def test_engine_stores_config(self):
        """Verify AcademicEngine stores config attribute."""
        from src.academic_v2.engine import AcademicEngine

        mock_llm = Mock()
        test_config = {"librarian": {"max_chunks": 50}}

        engine = AcademicEngine(mock_llm, config=test_config)

        self.assertEqual(engine.config, test_config,
            "Engine should store config attribute")
        print("[PASS] Fix 4b VERIFIED: AcademicEngine stores config")

    def test_engine_default_config(self):
        """Verify AcademicEngine works without config (uses defaults)."""
        from src.academic_v2.engine import AcademicEngine

        mock_llm = Mock()
        engine = AcademicEngine(mock_llm)

        self.assertEqual(engine.config, {},
            "Engine should default to empty config dict")
        print("[PASS] Fix 4c VERIFIED: AcademicEngine defaults to empty config")

    def test_config_yaml_has_librarian_section(self):
        """Verify config.yaml has librarian.max_chunks setting."""
        import yaml

        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                   'config', 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        self.assertIn('librarian', config,
            "config.yaml should have 'librarian' section")
        self.assertIn('max_chunks', config['librarian'],
            "librarian section should have 'max_chunks' key")
        # Note: max_chunks is now a safety ceiling (100), actual limit is derived from max_facts
        self.assertGreater(config['librarian']['max_chunks'], 0,
            "max_chunks should be positive")
        print("[PASS] Fix 4d VERIFIED: config.yaml has librarian.max_chunks setting")

    def test_chunk_limit_read_from_config(self):
        """Verify engine uses extraction_params for chunk limits (Phase 2 architecture)."""
        import inspect
        from src.academic_v2.engine import AcademicEngine

        # Check source code for new extraction_params pattern
        source = inspect.getsource(AcademicEngine)

        # Phase 2: Engine uses get_extraction_params for derived limits
        self.assertIn("get_extraction_params", source,
            "Engine should use get_extraction_params for extraction configuration")
        self.assertIn("extraction_params", source,
            "Engine should use extraction_params for chunk limits")
        self.assertIn("max_chunks", source,
            "Engine should reference max_chunks from extraction_params")
        print("[PASS] Fix 4e VERIFIED: Engine uses extraction_params for chunk limits")


class TestIntegration(unittest.TestCase):
    """Integration tests requiring more setup."""

    def test_sequential_rag_passes_config_to_engine(self):
        """Verify SequentialRAG passes config to AcademicEngine."""
        import inspect
        from src.retrieval.sequential_rag import SequentialRAG

        source = inspect.getsource(SequentialRAG)

        # Check that config is passed to AcademicEngine
        self.assertIn('config=self.pipeline.get("config"', source,
            "SequentialRAG should pass config to AcademicEngine")
        print("[PASS] Integration VERIFIED: Config passed from orchestrator to engine")


def run_all_tests():
    """Run all test classes and summarize results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestFix1SectionRestartFallback))
    suite.addTests(loader.loadTestsFromTestCase(TestFix2HyDEKnowledgeSource))
    suite.addTests(loader.loadTestsFromTestCase(TestFix3ProofreadingFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestFix4ConfigurableChunkLimit))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\n[SUCCESS] ALL TESTS PASSED - All 4 fixes verified!")
    else:
        print("\n[FAILED] SOME TESTS FAILED")
        for test, traceback in result.failures + result.errors:
            print(f"\nFailed: {test}")
            print(traceback)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
