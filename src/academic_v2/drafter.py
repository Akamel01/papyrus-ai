import logging
from typing import List, Dict, Any
from src.core.interfaces import LLMClient
from src.academic_v2.models import AtomicFact, ParagraphPlan

logger = logging.getLogger(__name__)


class Drafter:
    """
    Step 3: The Academic Drafter (The "Writer").
    Translates ParagraphPlan into prose using ONLY assigned facts.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def draft_section(self, plans: List[ParagraphPlan], all_facts: List[AtomicFact]) -> str:
        """
        Draft a full section by iterating through paragraph plans.
        """
        # Index facts for O(1) lookup
        facts_db = {f.id: f for f in all_facts}

        full_text = ""

        for plan in plans:
            paragraph = self.draft_paragraph(plan, facts_db)
            if paragraph:
                full_text += paragraph + "\n\n"

        return full_text.strip()

    def draft_paragraph(self, plan: ParagraphPlan, facts_db: Dict[str, AtomicFact]) -> str:
        """
        Draft a single paragraph based on the plan.
        """
        # Retrieve the actual fact objects
        relevant_facts = []

        # Handle plan as dict or object
        if isinstance(plan, dict):
            evidence_ids = plan.get("assigned_evidence", [])
            order = plan.get("order", "?")
            sec_name = plan.get("section_name", "Unknown")
            thesis = plan.get("thesis_statement", "")
            trans_in = plan.get("transition_in", "")
        else:
            evidence_ids = getattr(plan, "assigned_evidence", [])
            order = getattr(plan, "order", "?")
            sec_name = getattr(plan, "section_name", "Unknown")
            thesis = getattr(plan, "thesis_statement", "")
            trans_in = getattr(plan, "transition_in", "")

        for fid in evidence_ids:
            if fid in facts_db:
                relevant_facts.append(facts_db[fid])
            else:
                logger.warning(f"Drafter: Missing fact ID {fid} for paragraph {order}")

        if not relevant_facts:
            logger.warning(f"Drafter: Paragraph {order} has 0 valid facts (all evidence IDs dropped). Skipping.")
            return ""

        # ----------------------------------------------------------------------
        # FORMAT EVIDENCE FOR THE LLM (HUMAN-READABLE, NOT INTENDED TO BE OUTPUT)
        # C5 FIX: Include full APA citation so LLM can derive proper in-text citations
        # ----------------------------------------------------------------------
        evidence_str = ""
        for i, f in enumerate(relevant_facts):
            method_str = f"Method: {f.methodology.type.value}, {f.methodology.context}"
            # Provide the full APA citation so the LLM can derive (Author, Year) or Author (Year)
            citation_info = f.citation if f.citation else f"DOI: {f.source_id}"
            evidence_str += (
                f"({i+1}) Citation: {citation_info} | Year: {f.year}\n"
                f"      CLAIM: {f.claim_text} | "
                f"{method_str} | Certainty: {f.certainty.value}\n"
            )

        # ----------------------------------------------------------------------
        # PROMPT ENGINEERING - ENFORCE DEEP SYNTHESIS
        # C6 FIX: Unified APA in-text citation format (both forms)
        # P8 FIX: Dynamic word limit based on assigned evidence count
        # ----------------------------------------------------------------------
        num_facts = len(relevant_facts)
        # P17 FIX: Force dense synthesis. Lower multiplier, strict cap.
        word_min = max(200, min(400, num_facts * 15))
        word_max = max(350, min(500, num_facts * 25))
        system_prompt = f"""YOU ARE AN ACADEMIC WRITER. YOUR TASK IS TO PRODUCE ONE HIGH-QUALITY,
ANALYTICALLY RIGOROUS PARAGRAPH THAT INTEGRATES ALL PROVIDED EVIDENCE.

CRITICAL CONSTRAINTS (YOU MUST FOLLOW EACH ONE EXACTLY):
1. **NO EXTERNAL KNOWLEDGE** - USE ONLY THE PROVIDED CLAIMS.
2. **NO HALLUCINATIONS** - IF A FACT IS NOT LISTED, DO NOT INVENT IT.
3. **SYNTHESIZE EFFICIENTLY** - COMBINE RELATED FINDINGS INTO SINGLE SENTENCES WITH MULTIPLE CITATIONS WHERE LOGICAL, BUT AVOID OVERLY LENGTHY OR COMPLEX SENTENCES. IT IS ACCEPTABLE TO DEDICATE A CLEAR, CONCISE SENTENCE TO A SINGLE CRITICAL FACT IF NEEDED.
4. **METHODOLOGICAL LITERACY** - MENTION THE STUDY METHOD (E.G., "IN A SIMULATION STUDY, ...").
5. **CITE SOURCES USING APA IN-TEXT CITATIONS** - DERIVE THE AUTHOR NAME(S) AND YEAR FROM THE PROVIDED 'Citation' FIELD FOR EACH FACT. USE EITHER:
   - PARENTHETICAL FORM: (Author, Year) or (Author & Author, Year) or (Author et al., Year) AT THE END OF A STATEMENT.
   - NARRATIVE FORM: Author (Year) or Author and Author (Year) or Author et al. (Year) WHEN THE AUTHOR IS PART OF THE SENTENCE.
   CHOOSE THE FORM THAT BEST FITS THE SENTENCE STRUCTURE. FOR 3+ AUTHORS, USE "et al."
6. **INTEGRATE MULTIPLE SOURCES PER SENTENCE** - WHEN CLAIMS FROM DIFFERENT STUDIES ARE RELATED, MERGE THEM INTO THE SAME SENTENCE USING SEMICOLON-SEPARATED IN-TEXT CITATIONS (E.G., "... (Smith, 2020; Jones, 2021) ..."). DO NOT PLACE ONE CITATION PER SENTENCE.
7. **ANALYTICAL COMPARISON** - YOU MUST DIRECTLY COMPARE AND CONTRAST THE EVIDENCE, DISCUSSING AGREEMENTS, DISAGREEMENTS, STRENGTHS, WEAKNESSES, AND THE IMPACT OF DIFFERENT METHODOLOGIES ON THE CLAIMS.
8. **WORD LIMIT** - {word_min}-{word_max} WORDS.
9. **HEDGING** - APPLY APPROPRIATE HEDGING WHEN CERTAINTY IS LOW OR MODERATE.
10. **STRUCTURE** - START WITH THE PROVIDED TRANSITION/THESIS, THEN BUILD ONE LOGICALLY FLOWING ARGUMENT THAT WEAVES ALL EVIDENCE TOGETHER.

FAILING ANY CONSTRAINT WILL RESULT IN REJECTION."""
        # ----------------------------------------------------------------------
        # USER PROMPT - CLEAR INSTRUCTION SET
        # ----------------------------------------------------------------------
        user_prompt = f"""WRITE PARAGRAPH {order} FOR SECTION '{sec_name}'.

THESIS: {thesis}
TRANSITION IN: {trans_in or "None"}

ASSIGNED EVIDENCE:
{evidence_str}
INSTRUCTIONS:
- BEGIN WITH THE GIVEN TRANSITION/THESIS.
- INTEGRATE ALL EVIDENCE INTO ONE ANALYTICAL ARGUMENT.
- DERIVE IN-TEXT CITATIONS FROM THE 'Citation' FIELD (e.g., "Smith, J., & Jones, K. (2020). Title..." becomes "(Smith & Jones, 2020)" or "Smith and Jones (2020)").
- WHEN TWO OR MORE FACTS SUPPORT A POINT, MERGE THEM INTO THE SAME SENTENCE USING SEMICOLON-SEPARATED CITATIONS.
- COMPARE AND CONTRAST CLAIMS, METHODOLOGIES, AND CERTAINTY LEVELS.
- EMPHASIZE METHODOLOGICAL DETAILS TO ADD SCHOLARLY WEIGHT.
- APPLY HEDGING WHERE CERTAINTY IS LOW OR MODERATE.
- KEEP THE TOTAL WORD COUNT BETWEEN {word_min}-{word_max} WORDS.

WRITE THE PARAGRAPH NOW:"""

        try:
            # Slightly higher temperature for fluent prose but low enough for factual fidelity
            response = self.llm.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=2400,  # H2: was 600 (4×)
            )
            return response.strip()
        except Exception as e:
            logger.error(f"Drafter error: {e}")
            return f"[Error generating paragraph {order}]"