import json
import logging
import hashlib
import uuid
import inspect
import re
import concurrent.futures
from typing import List, Dict, Any, Optional

from src.core.interfaces import RetrievalResult, LLMClient
from src.academic_v2.models import (
    AtomicFact,
    Methodology,
    MethodologyType,
    CertaintyLevel,
)

logger = logging.getLogger(__name__)


class Librarian:
    """
    Step 1: Evidence Processing (The "Researcher").
    Extracts structured AtomicFacts from raw text chunks.
    """

    # ----------------------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------------------
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract_facts_from_chunks(self, chunks: List[RetrievalResult]) -> List[AtomicFact]:
        """
        Main entry point:
        1. Batch chunks (to fit context window).
        2. Extract facts in parallel (or sequential).
        3. Deduplicate and validate.
        """
        all_facts = []

        # 1. Create batches (default batch size = 3)
        batches = self._create_batches(chunks)
        logger.info(f"Librarian: Processing {len(chunks)} chunks in {len(batches)} batches")

        # 3. Deduplicate (simple ID check)
        # P21 FIX: Implement Concurrent Extraction with Fallbacks
        max_workers = 4
        retries = 2
        
        while retries >= 0 and batches:
            failed_batches = []
            logger.info(f"Librarian: Starting parallel extraction of {len(batches)} batches with {max_workers} workers.")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all batches
                future_to_batch = {
                    executor.submit(self._extract_batch, batch, True): batch for batch in batches
                }
                for future in concurrent.futures.as_completed(future_to_batch):
                    batch = future_to_batch[future]
                    try:
                        batch_facts = future.result()
                        all_facts.extend(batch_facts)
                    except Exception as e:
                        logger.warning(f"Librarian: Batch extraction failed ({e})")
                        failed_batches.append(batch)
            
            if failed_batches:
                retries -= 1
                batches = failed_batches
                max_workers = max(1, max_workers // 2)
                if retries >= 0:
                    logger.warning(f"Librarian: Retrying {len(batches)} failed batches with {max_workers} workers...")
            else:
                batches = []

        if batches:
            logger.warning(f"Librarian: {len(batches)} batches persistently failed. Executing sequential extraction safety net.")
            for batch in batches:
                batch_facts = self._extract_batch(batch, raise_errors=False)
                all_facts.extend(batch_facts)

        # 3. Deduplicate (simple ID check)
        unique_facts = self._deduplicate_facts(all_facts)

        logger.info(
            f"Librarian: Extracted {len(unique_facts)} unique facts from {len(chunks)} chunks"
        )
        return unique_facts

    # ----------------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------------
    def _create_batches(
        self, chunks: List[RetrievalResult], batch_size: int = None
    ) -> List[List[RetrievalResult]]:
        """Helper to create batches of chunks."""
        if batch_size is None:
            # P6 FIX: Dynamic batch size — target ~6-8 batches
            # Old: hardcoded 3 → 22 batches for 66 chunks (wasteful)
            # New: 66 // 6 = 11 per batch → 6 batches (3.6× faster)
            batch_size = min(10, max(3, len(chunks) // 6))
        return [chunks[i : i + batch_size] for i in range(0, len(chunks), batch_size)]

    # ----------------------------------------------------------------------
    # CITATION HELPERS
    # ----------------------------------------------------------------------
    _DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)

    def _extract_doi(self, text: str) -> Optional[str]:
        """Return the first DOI string found in `text` (if any)."""
        match = self._DOI_REGEX.search(text or "")
        return match.group(0) if match else None

    def _build_apa_citation(self, source: RetrievalResult) -> str:
        """
        Return a pre‑built APA citation from the Qdrant payload if available,
        otherwise construct a minimal one from metadata fields.
        FIX (H6): Prioritize stored `apa_reference` over manual construction.
        """
        meta = source.chunk.metadata

        # 1st: Check for pre-built APA in chunk metadata (from Qdrant payload)
        stored_apa = meta.get("apa_reference", "")
        if stored_apa:
            return stored_apa

        # 2nd: Fallback — construct manually from raw metadata
        authors = meta.get("authors")
        if isinstance(authors, list):
            authors_str = ", ".join(authors)
        else:
            authors_str = authors or "Unknown Author"

        year = meta.get("year") or "n.d."
        title = meta.get("title") or "Untitled"
        journal = meta.get("journal")
        volume = meta.get("volume")
        issue = meta.get("issue")
        pages = meta.get("pages")
        doi = meta.get("doi") or source.chunk.doi

        citation_parts = [f"{authors_str} ({year}). {title}."]
        if journal:
            vol_issue = ""
            if volume:
                vol_issue += volume
            if issue:
                vol_issue += f"({issue})"
            if vol_issue:
                citation_parts.append(f"{journal}, {vol_issue}")
            else:
                citation_parts.append(journal)
        if pages:
            citation_parts.append(pages)
        if doi:
            citation_parts.append(f"https://doi.org/{doi}")

        return " ".join(citation_parts).strip()

    # ----------------------------------------------------------------------
    # BATCH EXTRACTION
    # ----------------------------------------------------------------------
    def _extract_batch(self, batch: List[RetrievalResult], raise_errors: bool = False) -> List[AtomicFact]:
        """
        Send a batch of chunks to the LLM for extraction.
        """
        context_text = ""
        source_map: Dict[str, RetrievalResult] = {}

        for i, res in enumerate(batch):
            source_label = f"SOURCE_{i}"
            source_map[source_label] = res

            meta_str = (
                f"Source ID: {res.chunk.doi} | "
                f"Year: {res.chunk.metadata.get('year', 'Unknown')}"
            )
            context_text += (
                f"\n--- {source_label} ---\nMetadata: {meta_str}\nContent: {res.chunk.text}\n"
            )

        # ------------------------------------------------------------------
        # PROMPT DEFINITIONS (HEAVILY CONSTRAINED)
        # ------------------------------------------------------------------
        system_prompt = (
            "You are a **Research Librarian**. Your sole task is to extract **Atomic Facts** "
            "from scientific text and output them in **strict JSON**.\n\n"
            "CRITICAL RULES (MUST BE FOLLOWED EXACTLY):\n"
            "1. EXTRACT ONLY DISCRETE SCIENTIFIC CLAIMS.\n"
            "2. IGNORE NON‑SCIENTIFIC FLUFF.\n"
            "3. EVERY CLAIM MUST INCLUDE A **VALID CITATION** (APA‑style, DOI, or full reference) "
            "that directly references the source provided (use the DOI if available).\n"
            "4. IDENTIFY METHODOLOGY AND MAP IT TO ONE OF THE ENUM VALUES.\n"
            "5. ASSESS CERTAINTY: high / moderate / low.\n"
            "6. ASSIGN ONE OR MORE TOPICS.\n"
            "7. INCLUDE THE PUBLICATION YEAR (use the source metadata if omitted).\n"
            "8. OUTPUT **ONLY** THE JSON LIST – NO EXPLANATIONS, MARKDOWN, OR TEXT.\n"
            "9. JSON MUST CONTAIN THE FOLLOWING FIELDS FOR EACH OBJECT:\n"
            "   - source_label (string, matches one of the SOURCE_X labels above)\n"
            "   - citation (string, non‑empty and must contain the source DOI if possible)\n"
            "   - claim_text (string)\n"
            "   - methodology_type (string)\n"
            "   - methodology_context (string)\n"
            "   - topics (list of strings)\n"
            "   - certainty (string)\n"
            "   - year (integer)\n"
        )

        user_prompt = f"""Analyze the text below. **EXTRACT EVERY DISCRETE SCIENTIFIC CLAIM** and return them as a JSON list exactly matching the schema described in the system prompt.

TEXT TO ANALYZE:
{context_text}

RETURN ONLY THE JSON LIST."""
        # ------------------------------------------------------------------
        # LLM CALL
        # ------------------------------------------------------------------
        try:
            response_text = self.llm.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=16000,  # H2: was 4000 (4×)
            )
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            if raise_errors:
                raise e
            return []

        # ------------------------------------------------------------------
        # PARSE JSON (Centralized)
        # ------------------------------------------------------------------
        try:
            from src.utils.json_parser import parse_llm_json

            data = parse_llm_json(response_text, repair=True)
            if not isinstance(data, list):
                logger.warning(f"Librarian expected list, got {type(data)}")
                return []
        except Exception as e:
            logger.error(f"Failed to decode JSON: {e}")
            try:
                with open("debug_librarian_fail.txt", "w", encoding="utf-8") as f:
                    f.write(response_text)
            except Exception:
                pass
            return []

        # ------------------------------------------------------------------
        # CONVERT TO ATOMICFACT OBJECTS
        # ------------------------------------------------------------------
        facts = []
        for item in data:
            # ---- BASIC VALIDATION -------------------------------------------------
            raw_citation = item.get("citation", "").strip()
            source_label = item.get("source_label", "UNKNOWN")
            origin_res = source_map.get(source_label)

            # P1 FIX: ALWAYS use the authoritative APA citation from Qdrant metadata
            # LLM-generated citation field is unreliable (often returns bare DOIs,
            # causing downstream issues: DOIs as in-text citations, 0 cited refs, etc.)
            if origin_res:
                citation = self._build_apa_citation(origin_res)
            elif raw_citation:
                citation = raw_citation  # Last resort: use whatever LLM provided
            else:
                logger.warning(
                    f"No source and no citation for {source_label}, skipping."
                )
                continue

            # ---- SOURCE INFORMATION -------------------------------------------------
            source_id = (
                origin_res.chunk.doi if origin_res and hasattr(origin_res.chunk, "doi") else "unknown"
            )

            try:
                # ---- CLAIM TEXT ----------------------------------------------------
                claim_text = item.get("claim_text", "").strip()
                if not claim_text:
                    logger.warning("Skipping fact with empty claim_text.")
                    continue
                content_hash = hashlib.md5(claim_text.encode()).hexdigest()[:12]

                # ---- METHODOLOGY ----------------------------------------------------
                meth_type_raw = item.get("methodology_type", "other").lower()
                try:
                    meth_enum = MethodologyType(meth_type_raw)
                except ValueError:
                    # Map common hallucinations
                    if "conceptual" in meth_type_raw:
                        meth_enum = MethodologyType.THEORETICAL
                    else:
                        meth_enum = MethodologyType.OTHER

                # ---- CERTAINTY -------------------------------------------------------
                cert_raw = item.get("certainty", "moderate").lower()
                try:
                    cert_enum = CertaintyLevel(cert_raw)
                except ValueError:
                    cert_enum = CertaintyLevel.MODERATE

                # ---- YEAR ------------------------------------------------------------
                try:
                    year_val = int(
                        item.get("year")
                        or (origin_res.chunk.metadata.get("year") if origin_res else None)
                        or 0
                    )
                except Exception:
                    year_val = 0  # fallback; validation later may correct

                # ---- BUILD ATOMIC FACT -----------------------------------------------
                fact_kwargs: Dict[str, Any] = {
                    "id": f"fact_{content_hash}",
                    "source_id": source_id,
                    "claim_text": claim_text,
                    "excerpt_quote": item.get("excerpt_quote") or "Quote verification pending",
                    "methodology": Methodology(
                        type=meth_enum,
                        context=item.get("methodology_context", "Unspecified"),
                    ),
                    "topics": [
                        str(t).lower().replace(" ", "_") for t in item.get("topics", [])
                    ],
                    "certainty": cert_enum,
                    "year": year_val,
                    "citation": citation,
                }

                fact = AtomicFact(**fact_kwargs)
                facts.append(fact)

            except Exception as e:
                logger.warning(f"Skipping malformed fact: {e}")
                continue

        return facts

    # ----------------------------------------------------------------------
    # DEDUPLICATION
    # ----------------------------------------------------------------------
    def _deduplicate_facts(self, facts: List[AtomicFact]) -> List[AtomicFact]:
        """
        Deduplicate facts using ID (which is hash of claim text).
        """
        seen = set()
        unique: List[AtomicFact] = []
        for f in facts:
            if f.id not in seen:
                seen.add(f.id)
                unique.append(f)
        return unique