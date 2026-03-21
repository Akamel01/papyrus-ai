"""Unit tests for Manual Import Scanner.

Tests the multi-tier metadata extraction methodology and file handling.

Usage:
    pytest tests/test_manual_import.py -v
    pytest tests/test_manual_import.py --cov=src/streaming --cov-report=html
"""

import pytest
import tempfile
import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.streaming.manual_import import (
    ManualImportScanner,
    ManualImportResult,
    move_to_embedded,
    move_to_failed_parse,
)


class TestManualImportScanner:
    """Tests for ManualImportScanner core functionality."""

    @pytest.fixture
    def mock_paper_store(self):
        """Create a mock PaperStore."""
        store = MagicMock()
        store.status_exists.return_value = False
        store.add_paper.return_value = True
        return store

    @pytest.fixture
    def temp_import_dir(self):
        """Create temporary import directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import_dir = Path(tmpdir) / "ManualImport"
            import_dir.mkdir()
            yield import_dir

    def test_compute_file_checksum(self, mock_paper_store, temp_import_dir):
        """Test SHA256 checksum computation."""
        scanner = ManualImportScanner(mock_paper_store, temp_import_dir)

        # Create test file
        test_file = temp_import_dir / "test.pdf"
        test_content = b"test PDF content"
        test_file.write_bytes(test_content)

        checksum = scanner.compute_file_checksum(test_file)
        expected = hashlib.sha256(test_content).hexdigest()

        assert checksum == expected
        assert len(checksum) == 64  # SHA256 produces 64 hex chars

    def test_generate_unique_id(self, mock_paper_store, temp_import_dir):
        """Test unique_id generation format."""
        scanner = ManualImportScanner(mock_paper_store, temp_import_dir)

        unique_id = scanner.generate_unique_id("abc123def456")
        assert unique_id == "manual:abc123def456"
        assert unique_id.startswith("manual:")

    def test_idempotency_skip_duplicate(self, mock_paper_store, temp_import_dir):
        """Test that duplicate files are skipped."""
        # Mock find_by_checksum to return an existing embedded paper
        mock_existing = MagicMock()
        mock_existing.status = 'embedded'
        mock_existing.unique_id = 'manual:existing123'
        mock_paper_store.find_by_checksum.return_value = mock_existing

        scanner = ManualImportScanner(mock_paper_store, temp_import_dir)

        # Create minimal PDF-like file
        test_file = temp_import_dir / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 minimal test content")

        results = scanner.scan_and_register()

        assert len(results) == 1
        assert results[0].success == False
        assert "already" in results[0].error.lower() or "embedded" in results[0].error.lower()

    def test_scan_empty_directory(self, mock_paper_store, temp_import_dir):
        """Test scanning empty directory."""
        scanner = ManualImportScanner(mock_paper_store, temp_import_dir)
        results = scanner.scan_and_register()

        assert len(results) == 0

    def test_creates_subdirectories(self, mock_paper_store, temp_import_dir):
        """Test that embedded/ and failed_parse/ directories are created."""
        scanner = ManualImportScanner(mock_paper_store, temp_import_dir)

        assert (temp_import_dir / "embedded").exists()
        assert (temp_import_dir / "failed_parse").exists()

    def test_unique_id_prefix_constant(self, mock_paper_store, temp_import_dir):
        """Test that UNIQUE_ID_PREFIX is 'manual'."""
        scanner = ManualImportScanner(mock_paper_store, temp_import_dir)
        assert scanner.UNIQUE_ID_PREFIX == "manual"


class TestMetadataExtraction:
    """
    Comprehensive tests for PDF metadata extraction methodology.

    These tests verify each tier of the extraction strategy works correctly.
    """

    @pytest.fixture
    def scanner(self):
        """Create scanner with mock store."""
        mock_store = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            import_dir = Path(tmpdir) / "test"
            import_dir.mkdir()
            yield ManualImportScanner(mock_store, import_dir)

    # ═══════════════════════════════════════════════════════════════════
    # TIER 1: PDF Metadata Tests
    # ═══════════════════════════════════════════════════════════════════

    def test_parse_author_string_comma_separated(self, scanner):
        """Test parsing comma-separated author list."""
        result = scanner._parse_author_string("John Smith, Jane Doe, Bob Wilson")
        assert result == ["John Smith", "Jane Doe", "Bob Wilson"]

    def test_parse_author_string_semicolon_separated(self, scanner):
        """Test parsing semicolon-separated author list."""
        result = scanner._parse_author_string("John Smith; Jane Doe; Bob Wilson")
        assert result == ["John Smith", "Jane Doe", "Bob Wilson"]

    def test_parse_author_string_with_and(self, scanner):
        """Test parsing author list with 'and' separator."""
        result = scanner._parse_author_string("John Smith and Jane Doe")
        assert result == ["John Smith", "Jane Doe"]

    def test_parse_author_string_oxford_comma(self, scanner):
        """Test parsing author list with Oxford comma."""
        result = scanner._parse_author_string("John Smith, Jane Doe, and Bob Wilson")
        assert result == ["John Smith", "Jane Doe", "Bob Wilson"]

    def test_parse_author_string_last_first_format(self, scanner):
        """Test parsing 'Last, First' single author format."""
        result = scanner._parse_author_string("Smith, John")
        assert result == ["John Smith"]

    def test_parse_author_string_ampersand(self, scanner):
        """Test parsing author list with ampersand."""
        result = scanner._parse_author_string("John Smith & Jane Doe")
        assert result == ["John Smith", "Jane Doe"]

    def test_extract_year_from_pdf_date_standard(self, scanner):
        """Test extracting year from standard PDF date format."""
        result = scanner._extract_year_from_pdf_date("D:20230415120000")
        assert result == 2023

    def test_extract_year_from_pdf_date_short(self, scanner):
        """Test extracting year from short PDF date format."""
        result = scanner._extract_year_from_pdf_date("D:2021")
        assert result == 2021

    def test_extract_year_from_pdf_date_invalid(self, scanner):
        """Test handling invalid PDF date format."""
        result = scanner._extract_year_from_pdf_date("invalid")
        assert result is None

    def test_extract_year_from_pdf_date_with_embedded_year(self, scanner):
        """Test extracting year from string with embedded year."""
        result = scanner._extract_year_from_pdf_date("Created in 2019")
        assert result == 2019

    def test_is_generic_title_detects_generic(self, scanner):
        """Test detection of generic/useless titles."""
        assert scanner._is_generic_title("Untitled Document") == True
        assert scanner._is_generic_title("Microsoft Word - doc.docx") == True
        assert scanner._is_generic_title("PDF") == True
        assert scanner._is_generic_title("Page 1") == True
        assert scanner._is_generic_title("temp") == True
        assert scanner._is_generic_title("scan001") == True

    def test_is_generic_title_accepts_real_titles(self, scanner):
        """Test acceptance of real paper titles."""
        assert scanner._is_generic_title("Machine Learning in Healthcare: A Survey") == False
        assert scanner._is_generic_title("Deep Learning for Natural Language Processing") == False
        assert scanner._is_generic_title("Attention Is All You Need") == False

    # ═══════════════════════════════════════════════════════════════════
    # TIER 2: Text Analysis Tests
    # ═══════════════════════════════════════════════════════════════════

    def test_extract_title_from_text_standard_layout(self, scanner):
        """Test title extraction from standard academic paper layout."""
        text = """
        Machine Learning Approaches for Cancer Detection

        John Smith, Jane Doe
        University of Science

        Abstract
        This paper presents...
        """
        result = scanner._extract_title_from_text(text)
        assert result == "Machine Learning Approaches for Cancer Detection"

    def test_extract_title_from_text_skips_headers(self, scanner):
        """Test that header/footer patterns are skipped."""
        text = """
        Page 1
        DOI: 10.1234/example

        The Actual Paper Title Here

        Abstract
        """
        result = scanner._extract_title_from_text(text)
        assert result == "The Actual Paper Title Here"

    def test_extract_title_from_text_with_markdown_header(self, scanner):
        """Test title extraction from markdown-formatted PDF."""
        text = """
        # Deep Neural Networks for Image Classification

        Abstract
        """
        result = scanner._extract_title_from_text(text)
        assert result == "Deep Neural Networks for Image Classification"

    def test_extract_abstract_from_text(self, scanner):
        """Test abstract extraction from standard layout."""
        text = """
        Title Here

        Abstract

        This paper presents a novel approach to machine learning.
        We demonstrate improved performance on benchmark datasets.
        Our method achieves state-of-the-art results.

        Introduction

        Machine learning has...
        """
        result = scanner._extract_abstract_from_text(text)
        assert result is not None
        assert "novel approach" in result
        assert "Machine learning has" not in result  # Should stop at Introduction

    def test_extract_abstract_with_colon(self, scanner):
        """Test abstract extraction with 'Abstract:' format."""
        text = """
        Abstract: This is the abstract content that spans
        multiple lines and contains important information
        about the research presented in this paper.

        Keywords: machine learning, neural networks
        """
        result = scanner._extract_abstract_from_text(text)
        assert result is not None
        assert "abstract content" in result

    def test_extract_year_from_text_parentheses(self, scanner):
        """Test year extraction from parenthetical format."""
        text = "Published in Nature (2023). All rights reserved."
        result = scanner._extract_year_from_text(text)
        assert result == 2023

    def test_extract_year_from_text_copyright(self, scanner):
        """Test year extraction from copyright notice."""
        text = "© 2022 The Authors. Published by Elsevier."
        result = scanner._extract_year_from_text(text)
        assert result == 2022

    def test_extract_year_from_text_received_date(self, scanner):
        """Test year extraction from received date."""
        text = "Received: March 15, 2021. Accepted: June 20, 2021."
        result = scanner._extract_year_from_text(text)
        assert result == 2021

    def test_extract_authors_from_text_standard(self, scanner):
        """Test author extraction from standard name format."""
        text = """
        Deep Learning for NLP

        John Smith, Jane Doe, Bob Wilson
        Department of Computer Science
        """
        result = scanner._extract_authors_from_text(text)
        # Should find author-like names (implementation may vary)
        # At minimum, the function should return a list
        assert isinstance(result, list)

    # ═══════════════════════════════════════════════════════════════════
    # TIER 3: Filename Parsing Tests
    # ═══════════════════════════════════════════════════════════════════

    def test_clean_filename_doi_format(self, scanner):
        """Test cleaning DOI-format filename."""
        result = scanner._clean_filename_as_title("10.1234_article.name")
        assert "DOI:" in result
        assert "10.1234/article.name" in result

    def test_clean_filename_underscores(self, scanner):
        """Test cleaning filename with underscores."""
        result = scanner._clean_filename_as_title("some_paper_title_here")
        assert result == "some paper title here"

    def test_clean_filename_dashes(self, scanner):
        """Test cleaning filename with dashes."""
        result = scanner._clean_filename_as_title("some-paper-title-here")
        assert result == "some paper title here"

    def test_clean_filename_empty(self, scanner):
        """Test handling empty filename."""
        result = scanner._clean_filename_as_title("")
        assert result == "Untitled Document"

    def test_clean_filename_whitespace_only(self, scanner):
        """Test handling whitespace-only filename."""
        result = scanner._clean_filename_as_title("   ")
        assert result == "Untitled Document"

    # ═══════════════════════════════════════════════════════════════════
    # Confidence Calculation Tests
    # ═══════════════════════════════════════════════════════════════════

    def test_calculate_confidence_high(self, scanner):
        """Test high confidence with multiple sources."""
        metadata = {
            "extraction_sources": [
                "pdf_metadata:title",
                "pdf_metadata:author",
                "text_analysis:abstract",
                "text_analysis:year"
            ]
        }
        result = scanner._calculate_confidence(metadata)
        assert result == "high"

    def test_calculate_confidence_medium(self, scanner):
        """Test medium confidence with some sources."""
        metadata = {
            "extraction_sources": [
                "text_analysis:title",
                "text_analysis:abstract"
            ]
        }
        result = scanner._calculate_confidence(metadata)
        assert result == "medium"

    def test_calculate_confidence_low(self, scanner):
        """Test low confidence with fallbacks only."""
        metadata = {
            "extraction_sources": ["filename:title"]
        }
        result = scanner._calculate_confidence(metadata)
        assert result == "low"

    def test_calculate_confidence_empty(self, scanner):
        """Test confidence with no sources."""
        metadata = {"extraction_sources": []}
        result = scanner._calculate_confidence(metadata)
        assert result == "low"


class TestFileMovement:
    """Tests for file movement functions."""

    def test_move_to_embedded(self):
        """Test atomic move to embedded directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "test.pdf"
            source.write_text("test content")
            embedded_dir = Path(tmpdir) / "embedded"

            result = move_to_embedded(source, embedded_dir)

            assert result == True
            assert not source.exists()
            assert (embedded_dir / "test.pdf").exists()
            assert (embedded_dir / "test.pdf").read_text() == "test content"

    def test_move_to_embedded_creates_dir(self):
        """Test that embedded directory is created if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "test.pdf"
            source.write_text("test")
            embedded_dir = Path(tmpdir) / "nonexistent" / "embedded"

            result = move_to_embedded(source, embedded_dir)

            assert result == True
            assert embedded_dir.exists()
            assert (embedded_dir / "test.pdf").exists()

    def test_move_handles_collision(self):
        """Test that naming collisions are handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            embedded_dir = Path(tmpdir) / "embedded"
            embedded_dir.mkdir()

            # Create existing file
            (embedded_dir / "test.pdf").write_text("existing")

            # Try to move another file with same name
            source = Path(tmpdir) / "test.pdf"
            source.write_text("new")

            result = move_to_embedded(source, embedded_dir)

            assert result == True
            assert (embedded_dir / "test_1.pdf").exists()
            assert (embedded_dir / "test_1.pdf").read_text() == "new"
            assert (embedded_dir / "test.pdf").read_text() == "existing"

    def test_move_handles_multiple_collisions(self):
        """Test handling multiple naming collisions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            embedded_dir = Path(tmpdir) / "embedded"
            embedded_dir.mkdir()

            # Create existing files
            (embedded_dir / "test.pdf").write_text("v0")
            (embedded_dir / "test_1.pdf").write_text("v1")
            (embedded_dir / "test_2.pdf").write_text("v2")

            # Try to move another file
            source = Path(tmpdir) / "test.pdf"
            source.write_text("v3")

            result = move_to_embedded(source, embedded_dir)

            assert result == True
            assert (embedded_dir / "test_3.pdf").exists()
            assert (embedded_dir / "test_3.pdf").read_text() == "v3"

    def test_move_to_failed_parse(self):
        """Test move to failed_parse directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "bad.pdf"
            source.write_text("corrupted")
            failed_dir = Path(tmpdir) / "failed_parse"

            result = move_to_failed_parse(source, failed_dir)

            assert result == True
            assert not source.exists()
            assert (failed_dir / "bad.pdf").exists()

    def test_move_nonexistent_file(self):
        """Test moving a file that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "nonexistent.pdf"
            embedded_dir = Path(tmpdir) / "embedded"

            result = move_to_embedded(source, embedded_dir)

            assert result == False


class TestManualImportResult:
    """Tests for ManualImportResult dataclass."""

    def test_result_success(self):
        """Test successful result creation."""
        result = ManualImportResult(
            pdf_path=Path("/test/file.pdf"),
            unique_id="manual:abc123",
            success=True,
            checksum="abc123"
        )
        assert result.success == True
        assert result.error is None
        assert result.checksum == "abc123"

    def test_result_failure(self):
        """Test failure result creation."""
        result = ManualImportResult(
            pdf_path=Path("/test/file.pdf"),
            unique_id="manual:abc123",
            success=False,
            error="File corrupted",
            checksum="abc123"
        )
        assert result.success == False
        assert result.error == "File corrupted"


class TestIntegration:
    """Integration tests requiring actual PDF files."""

    @pytest.fixture
    def real_pdf_path(self):
        """Get path to a real PDF for testing."""
        # Try ManualImport first, then Papers
        manual_dir = Path("DataBase/ManualImport")
        papers_dir = Path("DataBase/Papers")
        
        for test_dir in [manual_dir, papers_dir]:
            if test_dir.exists():
                pdfs = list(test_dir.glob("*.pdf"))
                if pdfs:
                    return pdfs[0]
        
        return None

    @pytest.mark.skipif(
        not Path("DataBase/Papers").exists() and not Path("DataBase/ManualImport").exists(),
        reason="Test PDFs not available"
    )
    def test_extract_metadata_real_pdf(self, real_pdf_path):
        """
        Integration test: Extract metadata from a real PDF.
        
        Run with: pytest -k "test_extract_metadata_real_pdf" -v
        """
        if real_pdf_path is None:
            pytest.skip("No test PDF available")

        mock_store = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = ManualImportScanner(mock_store, Path(tmpdir))
            
            result = scanner.extract_metadata_from_pdf(real_pdf_path)

            # Verify structure
            assert "title" in result
            assert "authors" in result
            assert "extraction_confidence" in result
            assert "extraction_sources" in result

            # Verify we got something
            assert result["title"] is not None
            assert len(result["extraction_sources"]) > 0

            # Log for manual verification
            print(f"\nExtracted metadata from {real_pdf_path.name}:")
            print(f"  Title: {result['title'][:60]}..." if result['title'] and len(result['title']) > 60 else f"  Title: {result['title']}")
            print(f"  Authors: {result['authors']}")
            print(f"  Year: {result['year']}")
            print(f"  Abstract: {'Yes' if result['abstract'] else 'No'}")
            print(f"  Confidence: {result['extraction_confidence']}")
            print(f"  Sources: {result['extraction_sources']}")
