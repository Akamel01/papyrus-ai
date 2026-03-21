"""
Proofreading Mixin for Sequential RAG.

Multi-pass proofreading system with 3 coordinated passes:
- Pass 1: Micro-level per section (grammar, clarity, tone)
- Pass 2: Macro-level structural review (redundancy, consistency)
- Pass 3: Targeted revision based on Pass 2 recommendations
"""

import re
import json
import logging
from typing import List, Dict, Tuple, Optional, Any
from src.utils.diagnostics import DiagnosticGate
from src.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)


class ProofreadingMixin:
    """
    Mixin providing multi-pass proofreading capabilities.
    
    Requires:
        - self.pipeline with "llm" key
    """
    
    def _multipass_proofread(
        self,
        response: str,
        apa_references: List[str],
        model: str,
        preset: dict,
        status_callback: callable = None,
        token_manager: Optional[Any] = None
    ) -> Tuple[str, List[str]]:
        """
        Multi-pass proofreading system with 3 coordinated passes.
        
        Pass 1: Micro-level per section (grammar, clarity, tone)
        Pass 2: Macro-level structural review (redundancy, consistency)
        Pass 3: Targeted revision based on Pass 2 recommendations
        
        Args:
            response: Complete response text with all sections
            apa_references: List of APA formatted references
            model: LLM model to use
            preset: Generation preset
            status_callback: Optional callback for status updates
            
        Returns:
            Tuple of (proofread_response, proofreading_notes)
            - proofread_response: The final proofread text
            - proofreading_notes: List of any fallback/error notes
        """
        proofreading_notes = []
        
        # Split response into sections
        sections = self._split_into_sections(response)
        if not sections:
            proofreading_notes.append("⚠️ Proofreading Note: Could not parse sections. Original content preserved.")
            return response, proofreading_notes
        
        logger.info(f"Multi-pass proofreading: {len(sections)} sections")
        
        # ========== PASS 1: Micro-level proofreading ==========
        if status_callback:
            status_callback("📝 Pass 1: Micro-level proofreading...")
        
        pass1_results = []
        
        for i, section in enumerate(sections):
            # Pass 1 now returns (revised_text, {}, error) - fingerprints generated in batch later
            with DiagnosticGate(
                f"Pass 1 (Section {i+1})", 
                severity="warning", 
                suppress=True
            ) as gate:
                # P4 FIX: Generous limit — section must be reproduced in full
                # Use char-based estimate (chars / 3 for Ollama tokenizer) + 50% headroom
                # Old: word_count * 1.5 * 1.2 = ~2700 tokens for 8K char sections → empty output
                p1_limit = max(10000, int(len(section) / 3 * 1.5))

                revised_text, _, error = self._proofread_pass1(section, i+1, model, max_tokens=p1_limit)
                if error:
                    proofreading_notes.append(f"⚠️ Pass 1 error (Section {i+1}): {error}. Original preserved.")
                    pass1_results.append(section)  # Fallback to original
                    # We don't raise here because we handled the fallback, but we log the warning via gate context
                    gate.context["error"] = error
                else:
                    pass1_results.append(revised_text)
                    gate.set_success_message(f"Pass 1: Micro-proofread Section {i+1}")
        
        # LATENCY OPTIMIZATION: Batch fingerprint extraction (single LLM call instead of N calls)
        if status_callback:
            status_callback("🔍 Extracting section fingerprints...")
        fingerprints = self._generate_fingerprints_batch(pass1_results, model)
        
        logger.info(f"Pass 1 + fingerprinting complete: {len(pass1_results)} sections")
        
        # ========== PASS 2: Macro-level structural review ==========
        if status_callback:
            status_callback("🔍 Pass 2: Structural review...")
        
        with DiagnosticGate(
            "Structural Review (Pass 2)", 
            severity="warning",
            suppress=True
        ) as gate:
            p2_limit = 4000
            if token_manager:
                p2_limit = token_manager.get_proofreading_limits("pass2_review", 0)
                
            change_plan, pass2_error = self._proofread_pass2(fingerprints, model, max_tokens=p2_limit)
            
            if not pass2_error:
                count = len(change_plan.get('edit_instructions', []))
                gate.context["instruction_count"] = count
                gate.set_success_message(f"Pass 2: Generated {count} edit instructions")
        
        if pass2_error:
            proofreading_notes.append(f"⚠️ Pass 2 (structural review) failed: {pass2_error}. Cross-section checks skipped.")
            # Return Pass 1 results combined
            final_response = "\n\n".join(pass1_results)
            return final_response, proofreading_notes
        
        logger.info(f"Pass 2 complete: {len(change_plan.get('edit_instructions', []))} edits planned")
        
        # ========== PASS 3a: Apply structural edits ==========
        if status_callback:
            status_callback("✏️ Pass 3a: Applying structural edits...")
        
        final_sections = list(pass1_results)  # Start with Pass 1 results
        
        applied_count = 0
        with DiagnosticGate(
            "Structural Edits (Pass 3a)", 
            severity="warning",
            suppress=True
        ) as gate:
            instructions = change_plan.get("edit_instructions", [])
            for instruction in instructions:
                target_section = instruction.get("target_section", 0) - 1  # 0-indexed
                if 0 <= target_section < len(final_sections):
                    p3_limit = 10000
                    if token_manager:
                        input_est = len(final_sections[target_section].split()) * 1.5
                        p3_limit = token_manager.get_proofreading_limits("pass3a_structural", int(input_est))

                    revised, pass3a_error = self._proofread_pass3a(
                        final_sections[target_section],
                        instruction,
                        model,
                        max_tokens=p3_limit
                    )
                    if pass3a_error:
                        proofreading_notes.append(
                            f"⚠️ Pass 3a (Section {target_section+1}): {pass3a_error}"
                        )
                    else:
                        final_sections[target_section] = revised
                        applied_count += 1
            
            gate.context["applied_count"] = applied_count
            gate.set_success_message(f"Pass 3a: Applied {applied_count} structural edits")
        
        logger.info(f"Pass 3a complete: Structural edits applied")
        
        # NOTE: Pass 3b (flow enhancement) has been MERGED into Pass 3a
        # The Pass 3a prompt now includes conditional flow enhancement instructions
        
        final_response = "\n\n".join(final_sections)
        return final_response, proofreading_notes
    
    def _split_into_sections(self, response: str) -> List[str]:
        """Split response text into sections by ## headers."""
        section_pattern = r'(^## .+$)'
        parts = re.split(section_pattern, response, flags=re.MULTILINE)
        
        sections = []
        current_section = ""
        
        for part in parts:
            if re.match(r'^## ', part):
                if current_section.strip():
                    sections.append(current_section.strip())
                current_section = part
            else:
                current_section += part
        
        if current_section.strip():
            sections.append(current_section.strip())
        
        return sections
    
    def _proofread_pass1(
        self,
        section: str,
        section_num: int,
        model: str,
        max_tokens: int = 10000
    ) -> Tuple[str, dict, Optional[str]]:
        """
        Pass 1: Copy-editing for a single section.
        
        Returns plain text (not JSON with embedded content).
        Fingerprint is generated in a separate call.
        Includes length validation and retry logic.
        
        Returns:
            Tuple of (revised_text, fingerprint, error_message)
        """
        llm = self.pipeline["llm"]
        original_length = len(section)
        
        # ========== ATTEMPT 1: Full proofreading ==========
        prompt = f"""You are a COPY-EDITOR making MINIMAL corrections.

SECTION:
{section}

CORRECTIONS (ALL REQUIRED):
1. Fix grammar and syntax errors
2. Fix duplicate/repeated phrases
3. Remove redundant sentences (exact duplicates only)
4. Close unclosed citation parentheses

⚠️ PRESERVATION RULES:
- PRESERVE ALL content, numbers, statistics
- PRESERVE ALL citations exactly
- PRESERVE ALL LaTeX notation and special characters
- PRESERVE paragraph structure
- DO NOT summarize or condense
- DO NOT remove unique content
- TRUNCATION RULE: If the text ends with an incomplete sentence fragment, COMPLETE IT logically based on context.

Output MUST be SAME LENGTH (±10%) as input.
Return ONLY the corrected section text."""

        warning = None
        revised_text = section
        
        try:
            response = llm.generate(
                prompt=prompt,
                system_prompt="You are a copy-editor. Return only the corrected section, nothing else.",
                temperature=0.2,
                max_tokens=max_tokens,
                model=model
            )
            
            revised_text = response.strip()
            
            # Length validation
            if len(revised_text) < 0.8 * original_length:
                warning = f"Attempt 1 produced short output ({len(revised_text)}/{original_length})"
                logger.warning(f"Pass 1 Section {section_num}: {warning}")
                
                # ========== ATTEMPT 2: Minimal proofreading ==========
                prompt2 = f"""Fix ONLY grammar errors and duplicate phrases. Keep everything else.

SECTION:
{section}

Return the corrected section. SAME LENGTH as input."""

                response2 = llm.generate(
                    prompt=prompt2,
                    system_prompt="Fix grammar only. Do not remove content.",
                    temperature=0.1,
                    max_tokens=max_tokens,  # P11 FIX: was p1_limit (undefined in this scope)
                    model=model
                )
                
                revised_text2 = response2.strip()
                
                if len(revised_text2) >= 0.8 * original_length:
                    revised_text = revised_text2
                    warning = f"⚠️ Section {section_num}: Fallback to minimal proofreading"
                else:
                    # ========== ATTEMPT 3: Return original ==========
                    revised_text = section
                    warning = f"⚠️ Section {section_num}: Proofreading truncated content, original preserved"
            
        except Exception as e:
            logger.warning(f"Pass 1 failed for section {section_num}: {e}")
            revised_text = section
            warning = f"⚠️ Section {section_num}: Proofreading error ({str(e)[:50]})"
        
        # LATENCY OPTIMIZATION: Skip per-section fingerprinting
        # Fingerprints are now generated in batch via _generate_fingerprints_batch()
        fingerprint = {}  # Empty - will be batch-generated
        
        return revised_text, fingerprint, warning
    
    def _generate_fingerprint(
        self,
        section: str,
        section_num: int,
        model: str
    ) -> dict:
        """Generate fingerprint metadata for a section (separate from proofreading)."""
        llm = self.pipeline["llm"]
        
        # Extract title from section
        title_match = re.match(r'^##\s+(.+)$', section, re.MULTILINE)
        title = title_match.group(1) if title_match else f"Section {section_num}"
        
        prompt = f"""Extract metadata from this section.

SECTION:
{section[:2000]}  # First 2000 chars for efficiency

OUTPUT (JSON):
{{
  "section_num": {section_num},
  "title": "{title}",
  "purpose": "2-3 sentence summary of what this section covers",
  "key_claims": ["claim1", "claim2", "claim3"],
  "key_terms": ["term1", "term2"]
}}

Return ONLY valid JSON."""

        try:
            response = llm.generate(
                prompt=prompt,
                system_prompt="Extract section metadata. Return only valid JSON.",
                temperature=0.1,
                max_tokens=4000,  # H2: was 1000 (4×)
                model=model
            )
            
            # Parse JSON
            clean_response = response.strip()
            if clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1]
                if clean_response.startswith("json"):
                    clean_response = clean_response[4:]
            clean_response = clean_response.strip()
            
            fingerprint = json.loads(clean_response)
            fingerprint["section_num"] = section_num
            return fingerprint
            
        except Exception as e:
            logger.warning(f"Fingerprint generation failed: {e}")
            return {
                "section_num": section_num,
                "title": title,
                "purpose": "Unknown",
                "key_claims": [],
                "key_terms": []
            }
    
    def _generate_fingerprints_batch(
        self,
        sections: List[str],
        model: str
    ) -> List[dict]:
        """
        Generate fingerprints for ALL sections in a single LLM call.
        
        LATENCY OPTIMIZATION: Reduces N separate LLM calls to 1 batched call.
        
        Args:
            sections: List of section texts (post-Pass 1 proofreading)
            model: LLM model to use
            
        Returns:
            List of fingerprint dicts, one per section
        """
        llm = self.pipeline["llm"]
        
        if not sections:
            return []
        
        # Build sections summary for prompt
        sections_text = ""
        for i, section in enumerate(sections, 1):
            # Extract title from section
            title_match = re.match(r'^##\s+(.+)$', section, re.MULTILINE)
            title = title_match.group(1) if title_match else f"Section {i}"
            # First 700 chars for efficiency
            preview = section[:700].replace('\n', ' ')
            sections_text += f"\n\n[SECTION {i}] {title}\n{preview}...\n"
        
        prompt = f"""Extract metadata for each section below.

{sections_text}

OUTPUT (JSON array with one object per section):
[
  {{"section_num": 1, "title": "...", "purpose": "1-2 sentences", "key_claims": ["claim1", "claim2"], "key_terms": ["term1"]}},
  {{"section_num": 2, ...}},
  ...
]

Return ONLY valid JSON array. One object per section."""

        # Use DiagnosticGate for robust error handling
        with DiagnosticGate(
            "Batch Fingerprinting",
            severity="error", 
            context={"sections_count": len(sections), "model": model},
            remediation="Check if LLM output was truncated due to token limits.",
            suppress=True  # ENABLED: Allow fallback to dummy fingerprints on failure
        ) as gate:
             # Add sections to context for debugging (will be sanitized)
             gate.context["sections_preview"] = [s[:100] for s in sections]
             
             try:
                response = llm.generate(
                    prompt=prompt,
                    system_prompt="Extract section metadata. Return only valid JSON array.",
                    temperature=0.1,
                    max_tokens=12000, # H2: was 3000 (4×)
                    model=model
                )
                
                # capture raw response in context for debugging
                gate.context["raw_response"] = response
                
                # Robust JSON parsing
                fingerprints = parse_llm_json(response, repair=True)
                
                if not isinstance(fingerprints, list):
                    logger.warning(f"Batch fingerprint parser returned {type(fingerprints)}, expected list")
                    fingerprints = []
                
                # Ensure we have one per section
                if len(fingerprints) < len(sections):
                    # Pad with dummies if needed
                    logger.warning(f"Fingerprint count mismatch ({len(fingerprints)} vs {len(sections)})")
                    for i in range(len(fingerprints), len(sections)):
                        fingerprints.append({
                            "section_num": i + 1,
                            "title": f"Section {i + 1}",
                            "error": True
                        })
                
                return fingerprints
                
             except json.JSONDecodeError as e:
                # Re-raise to trigger the gate, but gate will handle reporting
                # Re-raise to trigger the gate, but gate will handle reporting
                gate.context["json_error"] = str(e)
                raise e # DiagnosticGate in 'error' mode catches and reports this
             except Exception as e:
                raise e
             
             # Success (if no exception)
             gate.set_success_message(f"Extracted {len(fingerprints)} section fingerprints")
             return fingerprints

        # Fallback if gate suppresses exception or we need to return something
        return [{"section_num": i + 1, "title": f"Section {i + 1}", "error": True} for i in range(len(sections))]
    
    def _proofread_pass2(
        self,
        fingerprints: List[dict],
        model: str,
        max_tokens: int = 4000
    ) -> Tuple[dict, Optional[str]]:
        """
        Pass 2: Structural review using fingerprints.
        Produces edit instructions (no text changes).
        
        Returns:
            Tuple of (change_plan, error_message)
        """
        llm = self.pipeline["llm"]
        
        fingerprints_text = json.dumps(fingerprints, indent=2)
        
        prompt = f"""Review these section fingerprints for structural issues.

FINGERPRINTS:
{fingerprints_text}

IDENTIFY:
1. Redundancy (same claims in multiple sections)
2. Terminology inconsistencies
3. Missing transitions between sections

OUTPUT (JSON):
{{
  "redundancy_map": [
    {{"sections": [2, 5], "type": "partial", "description": "Both discuss crash reduction rates"}}
  ],
  "consistency_issues": [
    {{"section": 3, "issue": "Uses 'signalised' vs 'signalized' elsewhere"}}
  ],
  "edit_instructions": [
    {{
      "target_section": 5,
      "nature": "remove_redundancy",
      "specific_action": "Delete the sentence 'Crash rates decreased by 15%' which duplicates Section 2"
    }}
  ]
}}

⚠️ INSTRUCTION RULES:
- Instructions must be SPECIFIC and ACTIONABLE
- Specify EXACT text to change (e.g., "Delete sentence X" or "Replace 'signalised' with 'signalized'")
- NO vague instructions like "improve clarity" or "restructure"
- If no issues found, return empty arrays

Return ONLY valid JSON."""

        try:
            response = llm.generate(
                prompt=prompt,
                system_prompt="You are a structural editor. Return only valid JSON with specific edit instructions.",
                temperature=0.1,
                max_tokens=max_tokens,
                model=model
            )
            
            # Parse JSON using robust utility
            change_plan = parse_llm_json(response, repair=True)
            if not isinstance(change_plan, dict):
                logger.warning(f"Pass 2 parsed JSON is not a dict: type {type(change_plan)}")
                change_plan = {"edit_instructions": []}
            
            # Filter instructions to keep only actionable ones
            if "edit_instructions" in change_plan:
                change_plan["edit_instructions"] = [
                    inst for inst in change_plan["edit_instructions"]
                    if self._is_actionable_instruction(inst)
                ]
            
            return change_plan, None
            
        except json.JSONDecodeError as e:
            logger.warning(f"Pass 2 JSON parse error: {e}")
            return {"edit_instructions": []}, f"JSON parse error: {str(e)[:50]}"
        except Exception as e:
            logger.warning(f"Pass 2 failed: {e}")
            return {"edit_instructions": []}, str(e)[:100]
    
    def _is_actionable_instruction(self, instruction: dict) -> bool:
        """Filter out vague or dangerous instructions."""
        action = instruction.get('specific_action', instruction.get('action', ''))
        
        # Reject vague instructions
        vague_terms = ['improve', 'enhance', 'clarify', 'rewrite', 'restructure', 'reorganize']
        if any(term in action.lower() for term in vague_terms):
            logger.info(f"Filtering vague instruction: {action[:50]}")
            return False
        
        # Reject instructions targeting entire section
        if 'entire section' in action.lower() or 'whole section' in action.lower():
            logger.info(f"Filtering broad instruction: {action[:50]}")
            return False
        
        # Must have actual action text
        if len(action) < 10:
            return False
        
        return True
    
    def _proofread_pass3a(
        self,
        section: str,
        instruction: dict,
        model: str,
        max_tokens: int = 10000
    ) -> Tuple[str, Optional[str]]:
        """
        Pass 3a: Apply specific edit instruction to a section.
        Includes length validation.
        
        Returns:
            Tuple of (revised_section, error_message)
        """
        llm = self.pipeline["llm"]
        original_length = len(section)
        
        action = instruction.get('specific_action', instruction.get('action', 'make minimal edits'))
        
        prompt = f"""Apply this SPECIFIC edit to the section.

SECTION:
{section}

EDIT INSTRUCTION:
{action}

ADDITIONAL (only if needed after applying the edit):
- If sentences transition abruptly after your edit, add a brief transition word/phrase
- Examples: "However,", "Moreover,", "In contrast,", "Building on this,"
- Only add transitions where logical flow is disrupted by your edit

⚠️ CONSTRAINTS:
- Apply ONLY the specific edit above
- Add transitions ONLY if flow is disrupted (not by default)
- Make NO other changes to content, statistics, or citations
- Output MUST be similar length to input (±10%)

Return the edited section only."""

        try:
            revised = llm.generate(
                prompt=prompt,
                system_prompt="Apply the edit precisely. Return only the revised section.",
                temperature=0.2,
                max_tokens=max_tokens,
                model=model
            )
            
            revised_text = revised.strip()
            
            # Length validation - reject if too aggressive
            if len(revised_text) < 0.9 * original_length:
                logger.warning(f"Pass 3a edit too aggressive ({len(revised_text)}/{original_length}), keeping original")
                return section, f"⚠️ Edit rejected (output too short)"
            
            return revised_text, None
            
        except Exception as e:
            logger.warning(f"Pass 3a failed: {e}")
            return section, str(e)[:100]
    
    # Keep old method name for backward compatibility
    def _proofread_pass3(
        self,
        section: str,
        instruction: dict,
        model: str
    ) -> Tuple[str, Optional[str]]:
        """Backward compatible wrapper for Pass 3a."""
        return self._proofread_pass3a(section, instruction, model)
    
    def _proofread_response(
        self,
        response: str,
        apa_references: List[str],
        model: str,
        preset: dict,
        status_callback: callable = None,
        token_manager: Optional[Any] = None
    ) -> Tuple[str, List[str]]:
        """
        Main proofreading entry point.
        
        Uses the 3-pass multi-pass proofreading system.
        
        Returns:
            Tuple of (proofread_response, proofreading_notes)
        """
        return self._multipass_proofread(
            response=response,
            apa_references=apa_references,
            model=model,
            preset=preset,
            status_callback=status_callback,
            token_manager=token_manager
        )
