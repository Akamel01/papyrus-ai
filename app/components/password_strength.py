"""
SME Research Assistant - Password Strength Indicator Component

Provides real-time password strength feedback during registration and password changes.
"""
import re
import streamlit as st


def calculate_password_strength(password: str) -> dict:
    """
    Calculate password strength based on multiple criteria.

    Args:
        password: The password to evaluate

    Returns:
        dict with keys: score (0-100), level (weak/fair/good/strong),
        criteria (dict of individual checks)
    """
    if not password:
        return {
            "score": 0,
            "level": "empty",
            "criteria": {
                "length": False,
                "has_letter": False,
                "has_number": False,
                "has_upper": False,
                "has_lower": False,
                "has_special": False
            }
        }

    criteria = {
        "length": len(password) >= 12,
        "has_letter": bool(re.search(r'[a-zA-Z]', password)),
        "has_number": bool(re.search(r'\d', password)),
        "has_upper": bool(re.search(r'[A-Z]', password)),
        "has_lower": bool(re.search(r'[a-z]', password)),
        "has_special": bool(re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;\'`~]', password))
    }

    # Calculate score
    score = 0

    # Length scoring (0-40 points)
    if len(password) >= 16:
        score += 40
    elif len(password) >= 14:
        score += 30
    elif len(password) >= 12:
        score += 20
    elif len(password) >= 8:
        score += 10

    # Character variety scoring (0-60 points)
    if criteria["has_letter"]:
        score += 10
    if criteria["has_number"]:
        score += 15
    if criteria["has_upper"] and criteria["has_lower"]:
        score += 15
    if criteria["has_special"]:
        score += 20

    # Determine level
    if score >= 80:
        level = "strong"
    elif score >= 60:
        level = "good"
    elif score >= 40:
        level = "fair"
    else:
        level = "weak"

    return {
        "score": min(score, 100),
        "level": level,
        "criteria": criteria
    }


def render_password_strength_indicator(password: str) -> None:
    """
    Render a visual password strength indicator.

    Args:
        password: The password to evaluate
    """
    strength = calculate_password_strength(password)

    if strength["level"] == "empty":
        return

    # Color mapping
    colors = {
        "weak": "#ef4444",      # Red
        "fair": "#f59e0b",      # Amber
        "good": "#22c55e",      # Green
        "strong": "#10b981"     # Emerald
    }

    labels = {
        "weak": "Weak",
        "fair": "Fair",
        "good": "Good",
        "strong": "Strong"
    }

    color = colors.get(strength["level"], "#6b7280")
    label = labels.get(strength["level"], "")
    score = strength["score"]

    # Render the indicator
    st.markdown(f"""
    <div style="margin: 8px 0 16px 0;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <span style="font-size: 12px; color: #9ca3af;">Password strength</span>
            <span style="font-size: 12px; font-weight: 600; color: {color};">{label}</span>
        </div>
        <div style="background: #1f1f1f; border-radius: 4px; height: 6px; overflow: hidden;">
            <div style="
                width: {score}%;
                height: 100%;
                background: {color};
                border-radius: 4px;
                transition: all 0.3s ease;
            "></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Show criteria checklist
    criteria = strength["criteria"]

    def check_icon(passed: bool) -> str:
        if passed:
            return f'<span style="color: #22c55e;">&#10003;</span>'
        return f'<span style="color: #6b7280;">&#9675;</span>'

    st.markdown(f"""
    <div style="font-size: 11px; color: #9ca3af; margin-top: 8px;">
        <div style="display: flex; gap: 16px; flex-wrap: wrap;">
            <span>{check_icon(criteria["length"])} 12+ characters</span>
            <span>{check_icon(criteria["has_letter"])} Letters</span>
            <span>{check_icon(criteria["has_number"])} Numbers</span>
            <span>{check_icon(criteria["has_special"])} Special chars</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def validate_password_requirements(password: str) -> tuple[bool, str]:
    """
    Validate password meets minimum requirements.

    Args:
        password: The password to validate

    Returns:
        tuple of (is_valid, error_message)
    """
    if len(password) < 12:
        return False, "Password must be at least 12 characters"

    if not re.search(r'[a-zA-Z]', password):
        return False, "Password must contain at least one letter"

    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"

    return True, ""
