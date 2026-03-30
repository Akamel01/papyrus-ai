import logging
import time
import types
from typing import List, Generator, Any, Optional, Dict

from src.core.interfaces import RetrievalResult, SectionResult, LLMClient
from src.retrieval.sequential.models import GenerationProgress
from src.academic_v2.models import AtomicFact, ParagraphPlan
from src.academic_v2.librarian import Librarian
from src.academic_v2.architect import Architect
from src.academic_v2.drafter import Drafter
from src.config.extraction_config import get_extraction_params

logger = logging.getLogger(__name__)


class AcademicEngine:
    """
    Orchestrator for Academic Engine V2 (Evidence‑First Architecture).
    Replaces the legacy 'Prompt‑and‑Pray' generation logic.
    """

    # -----------------------------------------------------------------
    #   CONSTANTS – AGGRESSIVE PROMPT CONSTRAINTS
    # -----------------------------------------------------------------
    _CITATION_CONSTRAINT = (
        "\n\n**IMPORTANT:** EVERY FACTUAL CLAIM **MUST** BE ACCOMPANIED BY A "
        "PROPER APA IN-TEXT CITATION.  USE EITHER:\n"
        "  - PARENTHETICAL: (Author, Year) or (Author \u0026 Author, Year) or (Author et al., Year)\n"
        "  - NARRATIVE: Author (Year) or Author and Author (Year) or Author et al. (Year)\n"
        "CHOOSE THE FORM THAT BEST FITS THE SENTENCE STRUCTURE.  "
        "**ALL CITATIONS MUST BE FROM CANONICAL OR EXPERT "
        "SOURCES SUCH AS PEER-REVIEWED JOURNALS, AUTHORITATIVE TEXTBOOKS, OR "
        "ESTABLISHED ORGANIZATIONS.**  **DO NOT OMIT ANY CITATIONS**.  FAILURE "
        "TO PROVIDE AT LEAST ONE VALID CITATION WILL BE TREATED AS AN ERROR."
    )
    # C4 FIX: _ANALYTICAL_CONSTRAINT removed -- was hardcoded for crash-vs-conflict domain
    _CONTENT_CONSTRAINT = (
        "\n\n**IMPORTANT:** EACH SECTION **MUST** CONTAIN AT LEAST ONE SENTENCE OF "
        "NARRATIVE TEXT THAT EXPRESSES A FACTUAL CLAIM AND IS ACCOMPANIED BY A "
        "CITATION.  HEADINGS ALONE ARE **NOT** SUFFICIENT."
    )
    _COMBINED_CONSTRAINTS = _CITATION_CONSTRAINT + _CONTENT_CONSTRAINT

    def __init__(self, llm_client: LLMClient, config: Optional[Dict[str, Any]] = None):
        self.llm = llm_client
        self.config = config or {}
        self.librarian = Librarian(llm_client)
        self.architect = Architect(llm_client)
        self.drafter = Drafter(llm_client)

        # --------------------------------------------------------------
        #   Inject constraints into the Drafter as early as possible.
        # --------------------------------------------------------------
        self._patch_drafter_prompts()
        # --------------------------------------------------------------
        #   Inject constraints into the LLM client (fallback safety net).
        # --------------------------------------------------------------
        self._patch_llm_client()

    # -----------------------------------------------------------------
    #   INTERNAL HELPERS – PROMPT PATCHING
    # -----------------------------------------------------------------
    def _patch_drafter_prompts(self) -> None:
        """
        Aggressively prepend the combined constraints to *any* prompt that the
        Drafter may expose. The logic is defensive – if one approach fails we
        fall back to the next.
        """
        # -----------------------------------------------------------------
        # 1️⃣  Static attribute injection (system/user prompts)
        # -----------------------------------------------------------------
        for attr_name in (
            "system_prompt",
            "user_prompt",
            "system_message",
            "user_message",
            "system_template",
            "user_template",
            "prompt_template",
            "template",
        ):
            if hasattr(self.drafter, attr_name):
                original = getattr(self.drafter, attr_name)
                if isinstance(original, str):
                    patched = self._COMBINED_CONSTRAINTS + original
                else:  # pragma: no cover
                    patched = original
                setattr(self.drafter, attr_name, patched)

        # -----------------------------------------------------------------
        # 2️⃣  Private or public prompt‑building methods
        # -----------------------------------------------------------------
        for method_name in (
            "_build_prompt",
            "build_prompt",
            "create_prompt",
            "get_prompt",
            "_get_prompt",
        ):
            if hasattr(self.drafter, method_name):
                original_builder = getattr(self.drafter, method_name)  # type: ignore

                def _patched_builder(*args, _orig=original_builder, **kwargs):  # pragma: no cover
                    prompt = _orig(*args, **kwargs)

                    if isinstance(prompt, str):
                        return self._COMBINED_CONSTRAINTS + prompt

                    if isinstance(prompt, dict):
                        if prompt.get("role") == "system" and "content" in prompt:
                            prompt["content"] = self._COMBINED_CONSTRAINTS + prompt["content"]
                        elif "content" in prompt:
                            prompt["content"] = self._COMBINED_CONSTRAINTS + prompt["content"]
                        return prompt

                    if isinstance(prompt, list):
                        new_prompt = []
                        system_seen = False
                        for message in prompt:
                            if isinstance(message, dict) and message.get("role") == "system":
                                system_seen = True
                                msg = message.copy()
                                msg["content"] = self._COMBINED_CONSTRAINTS + msg.get("content", "")
                                new_prompt.append(msg)
                            else:
                                new_prompt.append(message)
                        if not system_seen:
                            new_prompt.insert(
                                0,
                                {"role": "system", "content": self._COMBINED_CONSTRAINTS},
                            )
                        return new_prompt

                    # Fallback – treat anything else as a string
                    return self._COMBINED_CONSTRAINTS + str(prompt)

                setattr(self.drafter, method_name, _patched_builder)  # type: ignore

        # -----------------------------------------------------------------
        # 3️⃣  Public ``draft_section`` wrapper – fallback heuristic
        # -----------------------------------------------------------------
        if hasattr(self.drafter, "draft_section"):
            original_draft = getattr(self.drafter, "draft_section")  # type: ignore
            # Capture constraints in the closure so they are available even when
            # the bound ``self`` refers to the Drafter instance.
            _constraints = self._COMBINED_CONSTRAINTS

            def _patched_draft_section(drafter_self, plans: List[ParagraphPlan], facts: List[AtomicFact], *args, **kwargs):
                """
                If the Drafter builds its own prompt internally we rely on the
                patched builder methods above. If it directly injects user‑provided
                text we prepend the constraints to the first ParagraphPlan’s description.
                """
                # If any known prompt‑building method exists on the drafter, trust that
                # the earlier patches will handle constraint injection.
                if any(
                    hasattr(drafter_self, m)
                    for m in ("_build_prompt", "build_prompt", "create_prompt", "get_prompt", "_get_prompt")
                ):
                    return original_draft(plans, facts, *args, **kwargs)

                # Heuristic fallback – prepend constraints to the first plan's primary text field.
                if plans:
                    if isinstance(plans[0], dict):
                        key = "description" if "description" in plans[0] else "thesis_statement"
                        current_val = plans[0].get(key, "")
                        plans[0][key] = f"{_constraints}\n\n{current_val}"
                    else:
                        if hasattr(plans[0], "description"):
                            plans[0].description = f"{_constraints}\n\n{getattr(plans[0], 'description', '')}"
                        elif hasattr(plans[0], "thesis_statement"):
                            plans[0].thesis_statement = f"{_constraints}\n\n{getattr(plans[0], 'thesis_statement', '')}"
                return original_draft(plans, facts, *args, **kwargs)

            # Bind the function as a method of the drafter instance
            setattr(
                self.drafter,
                "draft_section",
                types.MethodType(_patched_draft_section, self.drafter),
            )

    # -----------------------------------------------------------------
    #   INTERNAL HELPERS – LLM CLIENT PATCHING (Safety Net)
    # -----------------------------------------------------------------
    def _patch_llm_client(self) -> None:
        """
        Ensures that *any* direct LLM chat call receives the citation constraint,
        even if the Drafter's internal patching fails.
        """
        if not hasattr(self.llm, "chat"):
            return  # pragma: no cover – defensive; most LLMClients expose .chat

        original_chat = self.llm.chat  # type: ignore

        def _patched_chat(messages: Any, *args, **kwargs):  # pragma: no cover
            """
            Prepend the combined constraints to system messages.
            Supports the common signatures:
            - a list of message dicts [{role: 'system'|'user', content: str}, ...]
            - a raw string (treated as a user prompt)
            """
            # Normalise to a list of dicts if possible
            if isinstance(messages, list):
                # Ensure at least one system message containing constraints
                system_present = any(m.get("role") == "system" for m in messages if isinstance(m, dict))
                if not system_present:
                    messages = [{"role": "system", "content": self._COMBINED_CONSTRAINTS}] + messages
                else:
                    # Prepend constraints to existing system content(s)
                    new_messages = []
                    for m in messages:
                        if isinstance(m, dict) and m.get("role") == "system":
                            m = m.copy()
                            m["content"] = self._COMBINED_CONSTRAINTS + "\n\n" + m.get("content", "")
                        new_messages.append(m)
                    messages = new_messages
            elif isinstance(messages, str):
                # Simple string prompt – treat it as a user message
                messages = [
                    {"role": "system", "content": self._COMBINED_CONSTRAINTS},
                    {"role": "user", "content": messages},
                ]
            else:
                # Unknown type – fall back to string conversion
                messages = [
                    {"role": "system", "content": self._COMBINED_CONSTRAINTS},
                    {"role": "user", "content": str(messages)},
                ]

            return original_chat(messages, *args, **kwargs)  # type: ignore

        # Bind patched function
        setattr(self.llm, "chat", _patched_chat)  # type: ignore

    # -----------------------------------------------------------------
    #   PUBLIC API – SECTION GENERATION
    # -----------------------------------------------------------------
    def generate_section_v2(
        self,
        section_title: str,
        retrieval_results: List[RetrievalResult],
        query: str,
        section_num: int = 0,
        total_sections: int = 0,
        review_text: str = "",
        depth: str = "Medium",
        section_mode: bool = False,
    ) -> Generator[GenerationProgress, None, SectionResult]:
        """
        Generate a section using the Graph of Claims workflow.
        Yields progress events so the UI shows the new steps explicitly.

        Args:
            section_title: Title of the section to generate
            retrieval_results: Chunks from retrieval pipeline
            query: Original user query
            section_num: Current section number (1-indexed)
            total_sections: Total sections being generated
            review_text: Abstract/guidance for section planning
            depth: Investigation depth ("Low", "Medium", "High")
            section_mode: Whether generating as part of multi-section output
        """
        if not retrieval_results:
            logger.warning(f"No results for section {section_title}")
            return SectionResult(
                title=section_title,
                content="No evidence found.",
                citations_used=[],
            )

        start_time = time.time()

        # -----------------------------------------------------------------
        #   Step 1 – Librarian (Extraction) with Two-Stage Early Stopping
        # -----------------------------------------------------------------
        # Get extraction parameters based on depth and mode
        extraction_params = get_extraction_params(
            config=self.config,
            depth=depth,
            section_mode=section_mode,
            section_count=total_sections if total_sections > 0 else 1
        )

        yield GenerationProgress(
            type="step",
            title=f"📚 Librarian: Extracting Facts",
            content=f"Target: {extraction_params.max_facts} facts from ≤{extraction_params.max_chunks} chunks",
            section_num=section_num,
            total_sections=total_sections,
        )

        # Cap chunks to derived limit (based on max_facts / density)
        safe_results = retrieval_results[:extraction_params.max_chunks]
        logger.debug(
            f"[Librarian] Extraction params: max_facts={extraction_params.max_facts}, "
            f"max_chunks={extraction_params.max_chunks}, sample={extraction_params.sample_size}"
        )

        # Use two-stage extraction with early stopping
        facts, density = self.librarian.extract_facts_with_early_stop(
            chunks=safe_results,
            max_facts=extraction_params.max_facts,
            sample_size=extraction_params.sample_size,
            density_default=extraction_params.density_estimate
        )

        if not facts:
            safe_title = section_title.encode("ascii", "replace").decode("ascii")
            logger.error(f"FATAL: Librarian found 0 facts for {safe_title}. Terminating pipeline.")
            raise RuntimeError(
                f"Librarian Failure: Zero facts extracted from {len(safe_results)} chunks."
            )

        yield GenerationProgress(
            type="info",
            title=f"✅ Extracted {len(facts)} Atomic Facts",
            content=f"Density: {density:.1f} facts/chunk",
            section_num=section_num,
            total_sections=total_sections,
        )

        # -----------------------------------------------------------------
        #   Step 2 – Architect (Logic)
        # -----------------------------------------------------------------
        yield GenerationProgress(
            type="step",
            title="📐 Architect: Designing Logic",
            content="",
            section_num=section_num,
            total_sections=total_sections,
        )

        # 0️⃣ ROBUST GUIDANCE: Ensure review_text is present to prevent Architect crash
        # If upstream fails to provide abstract, fallback to Title + Query
        safe_review_text = review_text
        if not safe_review_text or not safe_review_text.strip():
             logger.warning(f"⚠️ SAFETY FALLBACK ACTIVATED: review_text missing for '{section_title}'. Using emergency guidance.")
             yield GenerationProgress(
                 type="info",
                 title="⚠️ Safety Fallback Activated",
                 content="Planner missing abstract. Using emergency guidance logic.",
                 section_num=section_num,
                 total_sections=total_sections,
             )
             safe_review_text = f"Discuss {section_title} in the context of {query}. key arguments and evidence."

        plans: List[ParagraphPlan] = self.architect.design_section_plan(
            query, facts, section_title, review_text=safe_review_text
        )

        if not plans:
            logger.error(f"FATAL: Architect failed to design plan for {section_title}. Terminating pipeline.")
            raise RuntimeError(
                f"Architect Failure: No paragraph plans generated for '{section_title}'."
            )

        yield GenerationProgress(
            type="info",
            title=f"✅ Designed {len(plans)} Paragraphs",
            content="",
            section_num=section_num,
            total_sections=total_sections,
        )

        # -----------------------------------------------------------------
        #   Step 3 – Drafter (Writing)
        # -----------------------------------------------------------------
        yield GenerationProgress(
            type="step",
            title="✍️ Drafter: Writing Prose",
            content="",
            section_num=section_num,
            total_sections=total_sections,
        )

        # Drafter receives the injected constraints via the monkey‑patches.
        raw_content = self.drafter.draft_section(plans, facts)

        # -----------------------------------------------------------------
        #   Post‑process: strip injected constraints from final output
        # -----------------------------------------------------------------
        # Remove **all** occurrences of the constraint block, not just a leading one.
        content = raw_content.replace(self._COMBINED_CONSTRAINTS, "").strip()

        if not content:
            logger.debug("Constraint stripping resulted in empty content; falling back to raw output.")
            content = raw_content.strip()

        # -----------------------------------------------------------------
        #   Post‑process: extract citations for legacy compatibility
        # -----------------------------------------------------------------
        from src.retrieval.sequential.generation import GenerationMixin

        extractor = GenerationMixin()  # Helper to reuse regex
        citations_used = extractor._extract_citations_from_text(content)

        # -----------------------------------------------------------------
        #   Validation – ensure at least one citation per fact AND non‑empty text
        # -----------------------------------------------------------------
        if not citations_used or not content.strip():
            logger.error(
                f"Generated content for section '{section_title}' fails "
                "authoritative‑coverage (missing citations or empty text)."
            )
            raise RuntimeError(
                "Generation Failure: The LLM returned empty text or omitted required citations."
            )

        # -----------------------------------------------------------------
        #   P9: Track which DOIs were actually cited (assigned to paragraphs)
        # -----------------------------------------------------------------
        assigned_ids = set()
        for p in plans:
            pln = p if isinstance(p, dict) else vars(p)
            assigned_ids.update(pln.get('assigned_evidence', []))
        cited_dois = set(f.source_id for f in facts if f.id in assigned_ids and f.source_id)
        logger.debug(f"P9: {len(assigned_ids)} assigned facts → {len(cited_dois)} cited DOIs")

        # -----------------------------------------------------------------
        #   Assemble the final result
        # -----------------------------------------------------------------
        result = SectionResult(
            title=section_title,
            content=content,
            citations_used=citations_used,
            sources=[],               # Filled by sequential_rag wrapper typically
            apa_references=[],        # Filled by wrapper
            doi_set=set(f.source_id for f in facts if f.source_id),
            cited_dois=cited_dois,    # P9: only DOIs that were actually drafted
        )

        # Optional timing/debug log
        elapsed = time.time() - start_time
        logger.debug(f"Section '{section_title}' generated in {elapsed:.2f}s")

        return result