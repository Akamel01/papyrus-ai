"""
LaTeX Equation Renderer for Streamlit.

Provides hybrid rendering: text via st.markdown, equations properly formatted.
Supports Greek letters, subscripts, superscripts, fractions, and symbols.
"""

import re
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class ContentPart:
    """A part of the response - either text or equation."""
    content: str
    is_equation: bool
    is_block: bool  # Block equation ($$...$$) vs inline ($...$)


def render_with_latex(text: str) -> str:
    """
    Process text to handle LaTeX equations for Streamlit display.
    
    Streamlit's st.markdown supports LaTeX with proper $ delimiters.
    This function detects undelimited LaTeX and wraps it properly.
    
    Handles:
    - [\boxed{\displaystyle ...}] - square bracket wrapped block equations
    - (\frac{...}{...}) - parenthesis wrapped inline equations  
    - Raw LaTeX commands like \frac{}{}, \text{}, etc.
    
    Args:
        text: Response text potentially containing LaTeX
        
    Returns:
        Formatted text ready for st.markdown
    """
    if not text:
        return text
        
    try:
        processed = text
        
        # PRIORITY 1: Handle [\boxed{...}] - block equations in square brackets
        boxed_bracket = r'\[\s*\\boxed\{(.+?)\}\s*\]'
        processed = re.sub(boxed_bracket, r'\n\n$$\1$$\n\n', processed, flags=re.DOTALL)
        
        # PRIORITY 2: Handle [\displaystyle ...] patterns  
        bracket_displaystyle = r'\[\s*\\displaystyle\s+(.+?)\s*\]'
        processed = re.sub(bracket_displaystyle, r'\n\n$$\1$$\n\n', processed, flags=re.DOTALL)
        
        # PRIORITY 3: Handle generic \[ ... \] and \( ... \) standard block/inline delimiters
        # Block math \[ ... \]
        processed = re.sub(r'\\\[(.*?)\\\]', r'\n\n$$\1$$\n\n', processed, flags=re.DOTALL)
        
        # Inline math \( ... \)
        # Use (?:(?!\n\n).)*? to match non-greedily without crossing paragraph boundaries
        processed = re.sub(r'\\\(((?:(?!\n\n).)*?)\\\)', r' $\1$ ', processed, flags=re.DOTALL)
        
        # PRIORITY 4: (Reserved - Old destructive bracket parsing removed)
        
        # PRIORITY 5: (Reserved - Old substring brute-force wrapper removed to prevent KaTeX fatal syntax errors on nested braces)
        
        # Ensure block equations have proper newlines for rendering
        def format_block_equation(match):
            eq = match.group(1).strip()
            return f"\n\n$$\n{eq}\n$$\n\n"
        
        processed = re.sub(
            r'\$\$\s*(.+?)\s*\$\$',
            format_block_equation,
            processed,
            flags=re.DOTALL
        )
        
        # For inline equations, ensure they have spaces around them
        processed = re.sub(
            r'(?<!\$)\$(?!\$)([^$]+)\$(?!\$)',
            lambda m: f' ${m.group(1).strip()}$ ',
            processed
        )
        
        return processed if processed else text
        
    except Exception:
        # Fallback to original text on any error
        return text


def split_for_hybrid_render(text: str) -> List[ContentPart]:
    """
    Split text into parts for hybrid rendering.
    
    Use this when st.markdown alone doesn't render equations properly.
    Each part can be rendered with the appropriate Streamlit function.
    
    Args:
        text: Text with potential LaTeX equations
        
    Returns:
        List of ContentPart objects
    """
    parts = []
    remaining = text
    
    # Pattern for block equations first (greedy)
    block_pattern = r'\$\$(.+?)\$\$'
    # Pattern for inline equations
    inline_pattern = r'(?<!\$)\$(?!\$)(.+?)\$(?!\$)'
    
    # Combined pattern to find all equations
    combined_pattern = r'(\$\$[^$]+\$\$|\$[^$]+\$)'
    
    last_end = 0
    for match in re.finditer(combined_pattern, text, re.DOTALL):
        # Add text before this equation
        if match.start() > last_end:
            text_part = text[last_end:match.start()]
            if text_part.strip():
                parts.append(ContentPart(
                    content=text_part,
                    is_equation=False,
                    is_block=False
                ))
        
        # Add the equation
        eq_text = match.group(1)
        is_block = eq_text.startswith('$$')
        
        # Extract just the equation content
        if is_block:
            eq_content = eq_text[2:-2].strip()
        else:
            eq_content = eq_text[1:-1].strip()
        
        parts.append(ContentPart(
            content=eq_content,
            is_equation=True,
            is_block=is_block
        ))
        
        last_end = match.end()
    
    # Add remaining text
    if last_end < len(text):
        remaining_text = text[last_end:]
        if remaining_text.strip():
            parts.append(ContentPart(
                content=remaining_text,
                is_equation=False,
                is_block=False
            ))
    
    return parts


def extract_equations(text: str) -> List[Tuple[str, bool]]:
    """
    Extract all equations from text.
    
    Args:
        text: Text containing potential LaTeX equations
        
    Returns:
        List of (equation, is_block) tuples
    """
    equations = []
    
    # Block equations ($$...$$)
    block_pattern = r'\$\$(.+?)\$\$'
    for match in re.finditer(block_pattern, text, re.DOTALL):
        equations.append((match.group(1).strip(), True))
    
    # Inline equations ($...$) - avoid matching $$
    inline_pattern = r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)'
    for match in re.finditer(inline_pattern, text):
        equations.append((match.group(1).strip(), False))
    
    return equations


def has_equations(text: str) -> bool:
    """Check if text contains LaTeX equations."""
    return bool(re.search(r'\$[^$]+\$', text))


# Common LaTeX symbols reference for prompts
LATEX_SYMBOLS = """
Greek letters: $\\alpha$, $\\beta$, $\\gamma$, $\\delta$, $\\theta$, $\\sigma$, $\\mu$
Subscripts: $V_{rel}$, $T_{c}$, $x_i$
Superscripts: $x^2$, $e^{-t}$
Fractions: $\\frac{a}{b}$, $\\frac{D}{V}$
Square roots: $\\sqrt{x}$, $\\sqrt[3]{x}$
Summation: $\\sum_{i=1}^{n} x_i$
Integration: $\\int_0^\\infty f(x) dx$
Limits: $\\lim_{x \\to 0}$
Comparison: $\\leq$, $\\geq$, $\\neq$, $\\approx$
Arrows: $\\rightarrow$, $\\leftarrow$, $\\Rightarrow$
"""
