"""
SME Research Assistant - Authentication Page

Login and registration interface.
"""
import streamlit as st
import sys
import logging
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.auth_helper import login, register, is_authenticated
from app.components.password_strength import (
    render_password_strength_indicator,
    validate_password_requirements
)


def render_auth_page():
    """Render the login/registration page."""
    logger.info("=== render_auth_page called ===")

    # Check if already authenticated
    if is_authenticated():
        logger.info("User already authenticated, rerunning")
        st.rerun()
        return

    logger.info("Rendering auth page for unauthenticated user")

    # Page styling
    st.markdown("""
    <style>
        /* Center the auth container */
        .auth-container {
            max-width: 400px;
            margin: 0 auto;
            padding: 2rem;
        }

        /* Hide Streamlit branding during auth */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}

        /* Auth form styling */
        .stTabs [data-baseweb="tab-list"] {
            gap: 2px;
            background-color: #1a1a1a;
            border-radius: 8px;
            padding: 4px;
        }

        .stTabs [data-baseweb="tab"] {
            background-color: transparent;
            border-radius: 6px;
            color: #9ca3af;
            padding: 10px 20px;
        }

        .stTabs [aria-selected="true"] {
            background-color: #333;
            color: #f59e0b;
        }

        /* Input styling */
        .stTextInput input {
            background-color: #1a1a1a !important;
            border: 1px solid #333 !important;
            border-radius: 8px !important;
            color: #e0e0e0 !important;
        }

        .stTextInput input:focus {
            border-color: #f59e0b !important;
            box-shadow: 0 0 0 1px #f59e0b !important;
        }

        /* Button styling */
        .stButton > button {
            background-color: #f59e0b !important;
            color: black !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 10px 24px !important;
            font-weight: 600 !important;
            width: 100% !important;
        }

        .stButton > button:hover {
            background-color: #d97706 !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h1 style="color: #f59e0b; margin-bottom: 0.5rem;">SME Research Assistant</h1>
        <p style="color: #6b7280; font-size: 14px;">Multi-User Research Platform</p>
    </div>
    """, unsafe_allow_html=True)

    # Auth tabs
    logger.info("Creating auth tabs (Login, Register)")
    tab1, tab2 = st.tabs(["Login", "Register"])
    logger.info("Tabs created successfully")

    with tab1:
        render_login_form()

    with tab2:
        render_register_form()


def render_login_form():
    """Render the login form."""
    with st.form("login_form", clear_on_submit=False):
        st.markdown("### Welcome back")

        identifier = st.text_input(
            "Username or Email",
            placeholder="Enter username or email",
            key="login_identifier"
        )

        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password",
            key="login_password"
        )

        submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            if not identifier or not password:
                st.error("Please enter your username/email and password")
            else:
                with st.spinner("Signing in..."):
                    success, message = login(identifier, password)

                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)


def render_register_form():
    """Render the registration form."""

    # Password field outside form for real-time strength indicator
    st.markdown("### Create an account")

    email = st.text_input(
        "Email",
        placeholder="you@example.com",
        key="register_email"
    )

    username = st.text_input(
        "Username (optional)",
        placeholder="e.g. johndoe  —  use this to sign in without email",
        key="register_username"
    )

    display_name = st.text_input(
        "Display Name (optional)",
        placeholder="Your name",
        key="register_name"
    )

    password = st.text_input(
        "Password",
        type="password",
        placeholder="Min. 12 characters with letters & numbers",
        key="register_password"
    )

    # Show password strength indicator in real-time
    if password:
        render_password_strength_indicator(password)

    password_confirm = st.text_input(
        "Confirm Password",
        type="password",
        placeholder="Re-enter your password",
        key="register_password_confirm"
    )

    if st.button("Create Account", use_container_width=True, key="register_submit"):
        # Validation
        if not email or not password:
            st.error("Email and password are required")
        elif password != password_confirm:
            st.error("Passwords do not match")
        else:
            # Validate password requirements (12+ chars, letters, numbers)
            is_valid, error_msg = validate_password_requirements(password)
            if not is_valid:
                st.error(error_msg)
            else:
                with st.spinner("Creating account..."):
                    success, message = register(
                        email=email,
                        username=username if username else None,
                        password=password,
                        display_name=display_name if display_name else None
                    )

                if success:
                    st.success("Account created! Redirecting...")
                    st.rerun()
                else:
                    st.error(message)
