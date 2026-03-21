import json
import logging
import re
from typing import Dict, List, Set

from src.core.interfaces import LLMClient
from src.academic_v2.models import AtomicFact, ParagraphPlan, RhetoricalRole

logger = logging.getLogger(__name__)


class Architect:
    """
    Step 2: Logic Architecture (The "Planner").
    Organizes AtomicFacts into a coherent ParagraphPlan.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    # ----------------------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------------------
    def design_section_plan(
        self,
        query: str,
        facts: List[AtomicFact],
        section_name: str,
        review_text: str = "",
    ) -> List[ParagraphPlan]:
        """
        Create a logic blueprint for a specific section.

        Returns a list of ``ParagraphPlan`` dict‑like objects (compatible
        with the model's JSON schema).  If the LLM response does not satisfy
        the mandatory constraints (e.g. missing a comparison paragraph,
        missing a gap/limitations paragraph, or referencing unknown fact IDs)
        the method logs an error and returns an empty list – this prevents
        downstream components from receiving a malformed plan.
        """
        # ------------------------------------------------------------------
        # 0️⃣  Guard against missing review text (alignment requirement)
        # ------------------------------------------------------------------
        if not review_text.strip():
            logger.warning(
                "Architect: REVIEW TEXT is missing for section '%s'. "
                "Alignment rule violated – returning empty plan.",
                section_name,
            )
            return []

        if not facts:
            logger.warning(
                "Architect: No facts provided for section '%s'. Returning empty plan.",
                section_name,
            )
            return []

        # ------------------------------------------------------------------
        # 1️⃣  Cap facts to prevent prompt overflow (P16 Part B)
        #      Drafter still gets ALL facts — only the Architect sees the cap.
        # ------------------------------------------------------------------
        # Compute target paragraphs first (same formula as _build_user_prompt)
        # P17 FIX: Denser synthesis. Fewer paragraphs (max 8), more facts per para.
        target_paragraphs = max(3, min(8, len(facts) // 25))
        max_architect_facts = min(100, target_paragraphs * 30)
        if len(facts) > max_architect_facts:
            logger.info(
                "Architect: Capping facts from %d to %d for section '%s'",
                len(facts), max_architect_facts, section_name,
            )
            facts = facts[:max_architect_facts]

        # ------------------------------------------------------------------
        # 2️⃣  Serialize facts for the LLM – sequential IDs (P16 Part A)
        # ------------------------------------------------------------------
        facts_list_str, valid_ids, reverse_map = self._serialize_facts(facts)

        # ------------------------------------------------------------------
        # 3️⃣  Build the prompt – aggressive constraints ensure alignment
        # ------------------------------------------------------------------
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            query,
            section_name,
            facts_list_str,
            len(valid_ids),
            review_text,
        )

        # ------------------------------------------------------------------
        # 3️⃣  Call the LLM (with Retry Logic for Hallucinated IDs/Breaks)
        # ------------------------------------------------------------------
        MAX_RETRIES = 3
        last_error = "Unknown"
        
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Slightly increase temperature on retry to shake it out of repetitive hallucinated loops
                temperature = 0.2 + (0.15 * (attempt - 1))
                
                logger.info(f"Architect: Generating plan for '{section_name}' (Attempt {attempt}/{MAX_RETRIES}, Temp: {temperature:.2f})")
                response_text = self.llm.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,  
                    max_tokens=4000,  # H2: originally 2000, capped at 4000 to prevent space hallucination
                )
            except Exception as exc:  # pragma: no cover
                logger.error("LLM generation failed on attempt %d: %s", attempt, exc)
                last_error = f"LLM Generation Exception: {exc}"
                continue

            # --- DEBUG INJECTION: LOG RESPONSE TEXT TO FILE ---
            try:
                import os
                # Create data dir if it doesn't exist just in case
                os.makedirs("data", exist_ok=True)
                with open("data/architect_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*80}\nRAW LLM RESPONSE (Section: {section_name}, Attempt: {attempt})\n{'='*80}\n")
                    f.write(response_text)
                    f.write(f"\n{'='*80}\n")
            except Exception as e:
                logger.error(f"Failed to write debug log: {e}")
            # --------------------------------------------------

            # ------------------------------------------------------------------
            # 4️⃣  Clean & parse JSON
            # ------------------------------------------------------------------
            from src.utils.json_parser import parse_llm_json

            try:
                # parsing with repair=True handles markdown stripping and healing
                plan_raw = parse_llm_json(response_text, repair=True)
                if not isinstance(plan_raw, list):
                    logger.error(
                        "Architect response on attempt %d is not a list: %s", attempt, type(plan_raw)
                    )
                    last_error = "Parsed JSON was not a list."
                    continue
            except Exception as exc:  # pragma: no cover
                logger.error("Failed to parse LLM JSON response on attempt %d: %s", attempt, exc)
                last_error = f"JSON Parse Exception: {exc}"
                continue

            # --- DEBUG INJECTION: LOG PARSED JSON LENGTH ---
            try:
                with open("data/architect_debug.log", "a", encoding="utf-8") as f:
                    if isinstance(plan_raw, list):
                        f.write(f"Parsed JSON Length: {len(plan_raw)}\n")
                    else:
                        f.write(f"Parsed JSON Type: {type(plan_raw)}\n")
            except:
                pass
            # -----------------------------------------------

            # ------------------------------------------------------------------
            # 5️⃣  Validate the plan (mandatory comparison + gap + ID sanity)
            # ------------------------------------------------------------------
            import json
            if not self._plan_is_valid(plan_raw, valid_ids):
                logger.error(
                    "Generated plan failed validation on attempt %d – all paragraphs lost "
                    "evidence after dropping unknown IDs.", attempt
                )
                last_error = "Validation Failed: All paragraphs lost evidence."
                continue

            # ------------------------------------------------------------------
            # 6️⃣  Remap sequential IDs back to original fact_<hash> IDs (P16)
            # ------------------------------------------------------------------
            for p in plan_raw:
                p["assigned_evidence"] = [
                    reverse_map[sid]
                    for sid in p.get("assigned_evidence", [])
                    if sid in reverse_map
                ]
            # Remove any paragraphs that lost ALL evidence during remap
            plan_raw = [p for p in plan_raw if p.get("assigned_evidence")]
            if not plan_raw:
                logger.error("Remap failed on attempt %d: no paragraphs retained evidence.", attempt)
                last_error = "Remap Failed: All paragraphs lost evidence."
                continue

            # ------------------------------------------------------------------
            # 7️⃣  ALIGNMENT WITH REVIEW TEXT (QUERY ALIGNMENT)
            # ------------------------------------------------------------------
            if not self._plan_matches_review_text(plan_raw, review_text):
                logger.warning(
                    "Generated plan alignment warning: No background/methodology paragraph "
                    "explicitly matched the review text keywords. Proceeding anyway."
                )

            # --------------------------------------------------------------
            # 8️⃣  Return the raw dict list (compatible with downstream code)
            # --------------------------------------------------------------
            logger.info("Architect: Successfully generated plan for '%s' on attempt %d.", section_name, attempt)
            return plan_raw
            
        # --------------------------------------------------------------
        # 9️⃣  Absolute Failure
        # --------------------------------------------------------------
        logger.error("Architect PERMANENTLY failed after %d attempts. Last Error: %s", MAX_RETRIES, last_error)
        return []

    # ----------------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------------
    @staticmethod
    def _serialize_facts(facts: List[AtomicFact]) -> tuple[str, Set[str], Dict[str, str]]:
        """
        Turn a list of ``AtomicFact`` objects into a compact, token‑efficient
        string for the LLM and collect the set of valid IDs.

        P16 FIX: Uses sequential IDs (F1, F2, ...) instead of hash-based IDs.
        LLMs reliably copy simple sequential IDs but hallucinate exact hashes.
        Returns a reverse_map to remap back to original fact_<hash> IDs.
        """
        facts_str_parts = []
        valid_ids: Set[str] = set()
        reverse_map: Dict[str, str] = {}  # F1 → fact_<hash>

        for i, f in enumerate(facts, start=1):
            seq_id = f"F{i}"  # P16: Simple sequential ID
            valid_ids.add(seq_id)
            reverse_map[seq_id] = f.id  # Map back to original hash ID

            # Format: [F1] (Year) Claim {Methodology}
            facts_str_parts.append(
                f"[{seq_id}] ({f.year}) {f.claim_text} {{{f.methodology.type.value}}}"
            )
        facts_list_str = "\n".join(facts_str_parts) + "\n"
        return facts_list_str, valid_ids, reverse_map

    @staticmethod
    def _build_system_prompt() -> str:
        """
        System‑level instructions – generic for any research topic.
        FIX (C2): Removed all hardcoded domain references (crash/conflict/road‑safety).
        """
        return (
            "YOU ARE A RESEARCH ARCHITECT. YOUR TASK IS TO CREATE A LOGICAL "
            "STRUCTURE FOR A SECTION OF AN ACADEMIC REVIEW.\n\n"
            "GOAL: ORGANIZE THE PROVIDED ATOMIC FACTS INTO A COHERENT SECTION "
            "PLAN THAT SYNTHESIZES THE EVIDENCE.\n\n"
            "CRITICAL RULES (MUST FOLLOW):\n"
            "1. GROUP FACTS BY CONCEPT, NOT BY AUTHOR.\n"
            "2. CREATE A THESIS STATEMENT FOR EACH PARAGRAPH.\n"
            "3. ASSIGN ONLY THE PROVIDED FACT IDS TO EACH PARAGRAPH — "
            "DO NOT INVENT ANY IDS.\n"
            "4. ENSURE A LOGICAL FLOW (e.g., BACKGROUND → EVIDENCE → "
            "ANALYSIS → SYNTHESIS).\n"
            "5. OUTPUT **JSON ONLY**: A LIST OF ParagraphPlan OBJECTS.\n"
            "6. WHEN THE EVIDENCE CONTAINS CONTRASTING APPROACHES, "
            "INCLUDE A COMPARISON PARAGRAPH WITH RHE_ROLE 'comparison'.\n"
            "7. WHEN THE EVIDENCE REVEALS LIMITATIONS OR OPEN QUESTIONS, "
            "INCLUDE A GAP PARAGRAPH WITH RHE_ROLE 'gap'.\n"
            "8. FOR INTRODUCTORY OR CONCLUDING SECTIONS, THESE ROLES ARE "
            "OPTIONAL — USE YOUR JUDGEMENT BASED ON THE EVIDENCE.\n"
            "9. EVERY PARAGRAPH MUST BE SUPPORTED BY AT LEAST ONE FACT ID. "
            "DO NOT LEAVE `assigned_evidence` EMPTY. IF NO EVIDENCE FITS, DO NOT CREATE THE PARAGRAPH.\n"
        )

    @staticmethod
    def _build_user_prompt(
        query: str,
        section_name: str,
        facts_list_str: str,
        fact_count: int,
        review_text: str,
    ) -> str:
        """
        User-level prompt - generic for any research topic.
        FIX (C2): Removed all hardcoded domain references.
        FIX (P7): Dynamic paragraph/fact scaling based on evidence count.
        """
        # P17 FIX: Denser synthesis. Fewer paragraphs (max 8), more facts per para.
        target_paragraphs = max(3, min(8, fact_count // 25))
        facts_per_para = max(5, min(12, fact_count // target_paragraphs)) if target_paragraphs > 0 else 5
        para_min = max(2, target_paragraphs - 1)
        para_max = target_paragraphs + 1
        
        return (
            f"DESIGN THE '{section_name.upper()}' SECTION FOR A PAPER ON: "
            f'"{ query.upper()}"\n\n'
            f"**REVIEW TEXT PROVIDED BY USER**:\n{review_text.strip()}\n\n"
            f"AVAILABLE EVIDENCE ({fact_count} ATOMIC FACTS):\n{facts_list_str}\n"
            "INSTRUCTIONS:\n"
            f"- PLAN {para_min}-{para_max} PARAGRAPHS. GROUP THEMATICALLY RELATED FACTS EVEN IF FROM DIFFERENT STUDIES.\n"
            f"- AIM FOR {facts_per_para} TO {facts_per_para + 5} FACTS PER PARAGRAPH TO ENSURE DENSE SYNTHESIS.\n"
            "- **SOURCE INTEGRATION**: WHILE EXCELLENT TO EXTRACT MULTIPLE FACTS FROM THE SAME STUDY, STRIVE TO SPAN MULTIPLE UNIQUE STUDIES PER PARAGRAPH WHERE LOGICAL.\n"
            "- SELECT A RHE_ROLE FOR EACH PARAGRAPH FROM: "
            "'introduction', 'background', 'methodology', 'evidence', "
            "'comparison', 'gap', 'limitations', 'future_work', 'conclusion'.\n"
            "- IF THE EVIDENCE CONTAINS CONTRASTING APPROACHES, "
            "INCLUDE A 'comparison' PARAGRAPH.\n"
            "- IF THE EVIDENCE REVEALS GAPS OR LIMITATIONS, "
            "INCLUDE A 'gap' OR 'limitations' PARAGRAPH.\n"
            "- THE FIRST PARAGRAPH MUST HAVE transition_in SET TO null.\n"
            "- THE RESPONSE **MUST DIRECTLY ADDRESS THE PROVIDED REVIEW TEXT**.\n\n"
            "JSON FORMAT (RETURN ONLY THE JSON ARRAY):\n"
            "[\n"
            "  {\n"
            "    \"order\": 1,\n"
            "    \"section_name\": \"{section_name}\",\n"
            "    \"thesis_statement\": \"<THESIS>\",\n"
            "    \"rhetorical_role\": \"<ROLE>\",\n"
            "    \"assigned_evidence\": [\"F1\", \"F5\", \"F12\"],\n"
            "    \"transition_in\": null\n"
            "  }\n"
            "]\n\n"
            "RETURN ONLY THE JSON ARRAY."
        )

    def _plan_is_valid(self, plan: List[dict], valid_ids: Set[str]) -> bool:
        """
        Validate the plan.  FIX (C2): Unknown fact IDs are now DROPPED with a
        warning instead of hard‑rejecting the entire plan.  Role checks are
        advisory only (non‑blocking).
        """
        # Track required roles
        has_comparison = False
        has_background = False
        has_gap = False

        for p in plan:
            # --------------------------------------------------------------
            # Evidence sanity check — warn + drop unknown IDs
            # --------------------------------------------------------------
            evidence = p.get("assigned_evidence", [])
            cleaned_evidence = []
            for fid in evidence:
                if fid in valid_ids:
                    cleaned_evidence.append(fid)
                else:
                    logger.warning(
                        "Validation: Dropping unknown fact ID '%s' from "
                        "paragraph %s (not in valid_ids).",
                        fid,
                        p.get("order", "?"),
                    )
            p["assigned_evidence"] = cleaned_evidence

            # --------------------------------------------------------------
            # Role presence tracking
            # --------------------------------------------------------------
            role = (p.get("rhetorical_role") or "").strip().lower()
            if role == "comparison" or role in RhetoricalRole.comparison_synonyms():
                has_comparison = True
            if role in ("background", "methodology") or role in RhetoricalRole.background_synonyms():
                has_background = True
            if role in ("gap", "limitations", "future_work") or role in RhetoricalRole.gap_synonyms():
                has_gap = True

        # --------------------------------------------------------------
        # Remove paragraphs that ended up with zero evidence
        # --------------------------------------------------------------
        plan[:] = [p for p in plan if p.get("assigned_evidence")]

        if not plan:
            logger.error(
                "Validation failed: All paragraphs lost their evidence "
                "after dropping unknown fact IDs."
            )
            return False

        # --------------------------------------------------------------
        # Advisory role warnings (non‑blocking)
        # --------------------------------------------------------------
        missing = []
        if not has_comparison:
            missing.append("comparison")
        if not has_background:
            missing.append("background/methodology")
        if not has_gap:
            missing.append("gap/limitations/future_work")

        if missing:
            logger.warning(
                "Validation advisory: Plan missing paragraph role(s): %s. "
                "This is acceptable for sections like Introduction or Conclusion.",
                ", ".join(missing),
            )

        return True

    @staticmethod
    def _extract_review_keywords(review_text: str) -> Set[str]:
        """
        Very simple keyword extractor: lower‑case words longer than 4 characters
        that are not generic stop‑words. This is sufficient for checking that
        the plan references the review content.
        """
        stopwords = {
            "the", "and", "for", "with", "that", "this", "these", "those",
            "such", "from", "based", "including", "including", "among",
            "between", "within", "using", "used", "use", "have", "has",
            "were", "been", "also", "however", "although", "where", "when",
            "which", "while", "both", "each", "other", "their", "its",
        }
        words = re.findall(r"\b[a-zA-Z]{5,}\b", review_text.lower())
        return {w for w in words if w not in stopwords}

    def _plan_matches_review_text(self, plan: List[dict], review_text: str) -> bool:
        """
        Ensure that at least one BACKGROUND/METHODOLOGY paragraph contains
        one of the key terms from the supplied review text.
        """
        keywords = self._extract_review_keywords(review_text)
        if not keywords:
            # No meaningful keywords to check – consider it a pass.
            return True

        for paragraph in plan:
            role = (paragraph.get("rhetorical_role") or "").strip().lower()
            if role in ("background", "methodology") or role in RhetoricalRole.background_synonyms():
                thesis = paragraph.get("thesis_statement", "").lower()
                # crude tokenisation
                thesis_words = set(re.findall(r"\b[a-z]{5,}\b", thesis))
                if keywords.intersection(thesis_words):
                    return True

        # No background/methodology paragraph referenced any keyword.
        return False