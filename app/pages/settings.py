"""
SME Research Assistant - Settings Page

User settings, API key management, and preferences.
"""
import streamlit as st
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.auth_helper import (
    is_authenticated,
    get_current_user,
    get_api_keys,
    save_api_key,
    delete_api_key,
    get_preferences,
    update_preferences,
    change_password,
    logout
)


def render_settings_page():
    """Render the settings page."""

    # Require authentication
    if not is_authenticated():
        st.warning("Please login to access settings.")
        st.stop()
        return

    user = get_current_user()
    if not user:
        st.error("Could not load user information")
        return

    st.title("Settings")

    # User info header
    st.markdown(f"""
    <div style="background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem;">
        <div style="display: flex; align-items: center; gap: 1rem;">
            <div style="width: 48px; height: 48px; background: linear-gradient(135deg, #f59e0b, #d97706);
                        border-radius: 50%; display: flex; align-items: center; justify-content: center;
                        font-size: 20px; font-weight: bold; color: black;">
                {user.display_name[0].upper() if user.display_name else user.email[0].upper()}
            </div>
            <div>
                <h3 style="margin: 0; color: #e0e0e0;">{user.display_name or 'User'}</h3>
                <p style="margin: 0; color: #6b7280; font-size: 14px;">{user.email}</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Settings sections
    tab1, tab2, tab3 = st.tabs(["API Keys", "Preferences", "Account"])

    with tab1:
        render_api_keys_section()

    with tab2:
        render_preferences_section()

    with tab3:
        render_account_section(user)


def render_api_keys_section():
    """Render API key management section."""

    st.markdown("### API Keys")
    st.markdown("""
    <p style="color: #6b7280; font-size: 14px; margin-bottom: 1.5rem;">
        Store your API keys securely. Keys are encrypted at rest and only decrypted when needed.
    </p>
    """, unsafe_allow_html=True)

    # Load existing keys
    existing_keys = get_api_keys()
    existing_key_names = {k["key_name"] for k in existing_keys}

    # Available key types
    key_types = [
        {
            "name": "openalex",
            "display": "OpenAlex",
            "description": "Free API for academic paper metadata",
            "url": "https://openalex.org/"
        },
        {
            "name": "semantic_scholar",
            "display": "Semantic Scholar",
            "description": "AI-powered academic search and citation analysis",
            "url": "https://www.semanticscholar.org/product/api"
        },
        {
            "name": "ollama_cloud",
            "display": "Ollama Cloud",
            "description": "Cloud-hosted LLM inference (optional)",
            "url": "https://ollama.com/"
        }
    ]

    # Display each key type
    for key_type in key_types:
        has_key = key_type["name"] in existing_key_names
        existing = next((k for k in existing_keys if k["key_name"] == key_type["name"]), None)

        with st.container():
            col1, col2 = st.columns([3, 1])

            with col1:
                # Use Unicode symbols instead of SVG for better Streamlit compatibility
                status_icon = "✓" if has_key else "○"
                status_color = "#22c55e" if has_key else "#6b7280"

                st.markdown(f"""
                <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">
                    <span style="font-size: 18px; color: {status_color}; width: 20px; text-align: center;">{status_icon}</span>
                    <span style="font-weight: 600; color: #e0e0e0;">{key_type["display"]}</span>
                    {f'<span style="color: #6b7280; font-size: 12px;">({existing["masked_value"]})</span>' if existing else ''}
                </div>
                <p style="color: #6b7280; font-size: 13px; margin: 0 0 0 2rem;">
                    {key_type["description"]}
                    <a href="{key_type["url"]}" target="_blank" style="color: #f59e0b;">Get API key</a>
                </p>
                """, unsafe_allow_html=True)

            with col2:
                action_label = "Update" if has_key else "Add"
                if st.button(action_label, key=f"btn_{key_type['name']}", use_container_width=True):
                    st.session_state[f"editing_{key_type['name']}"] = True

            # Show input form if editing
            if st.session_state.get(f"editing_{key_type['name']}", False):
                with st.form(f"key_form_{key_type['name']}"):
                    new_value = st.text_input(
                        f"Enter {key_type['display']} API Key",
                        type="password",
                        placeholder="Paste your API key here",
                        key=f"input_{key_type['name']}"
                    )

                    col_save, col_cancel, col_delete = st.columns([2, 2, 1])

                    with col_save:
                        if st.form_submit_button("Save", use_container_width=True):
                            if new_value:
                                success, msg = save_api_key(key_type["name"], new_value)
                                if success:
                                    st.success(msg)
                                    st.session_state[f"editing_{key_type['name']}"] = False
                                    st.rerun()
                                else:
                                    st.error(msg)
                            else:
                                st.error("Please enter a key value")

                    with col_cancel:
                        if st.form_submit_button("Cancel", use_container_width=True):
                            st.session_state[f"editing_{key_type['name']}"] = False
                            st.rerun()

                    with col_delete:
                        if has_key:
                            if st.form_submit_button("Delete", use_container_width=True):
                                success, msg = delete_api_key(key_type["name"])
                                if success:
                                    st.success(msg)
                                    st.session_state[f"editing_{key_type['name']}"] = False
                                    st.rerun()
                                else:
                                    st.error(msg)

            st.markdown("<hr style='border-color: #333; margin: 1rem 0;'>", unsafe_allow_html=True)


def render_preferences_section():
    """Render user preferences section."""

    st.markdown("### Research Preferences")

    # Load current preferences
    prefs = get_preferences()

    with st.form("preferences_form"):
        # Preferred model
        model_options = [
            "gpt-oss:120b-cloud",
            "qwen2.5:72b",
            "llama3.1:70b",
            "mistral-large"
        ]
        current_model = prefs.get("preferred_model", "gpt-oss:120b-cloud")
        if current_model not in model_options:
            model_options.insert(0, current_model)

        preferred_model = st.selectbox(
            "Preferred Model",
            options=model_options,
            index=model_options.index(current_model) if current_model in model_options else 0,
            help="Default LLM for research queries"
        )

        # Research depth
        depth_options = ["comprehensive", "balanced", "quick"]
        current_depth = prefs.get("research_depth", "comprehensive")

        research_depth = st.selectbox(
            "Default Research Depth",
            options=depth_options,
            index=depth_options.index(current_depth) if current_depth in depth_options else 0,
            help="How thorough the research should be by default"
        )

        # Citation style
        citation_options = ["apa", "mla", "chicago", "ieee"]
        current_citation = prefs.get("citation_style", "apa")

        citation_style = st.selectbox(
            "Citation Style",
            options=citation_options,
            index=citation_options.index(current_citation) if current_citation in citation_options else 0,
            help="Format for academic citations"
        )

        # Ollama mode
        ollama_options = ["server", "cloud", "local"]
        current_ollama = prefs.get("ollama_mode", "server")

        ollama_mode = st.selectbox(
            "Ollama Mode",
            options=ollama_options,
            index=ollama_options.index(current_ollama) if current_ollama in ollama_options else 0,
            help="Server: Use shared server | Cloud: Your Ollama Cloud account | Local: Your local Ollama"
        )

        if st.form_submit_button("Save Preferences", use_container_width=True):
            success, msg = update_preferences({
                "preferred_model": preferred_model,
                "research_depth": research_depth,
                "citation_style": citation_style,
                "ollama_mode": ollama_mode
            })

            if success:
                st.success("Preferences saved!")
            else:
                st.error(msg)


def render_account_section(user):
    """Render account management section."""

    st.markdown("### Account Settings")

    # Change password
    st.markdown("#### Change Password")

    with st.form("password_form"):
        current_password = st.text_input(
            "Current Password",
            type="password",
            placeholder="Enter current password"
        )

        new_password = st.text_input(
            "New Password",
            type="password",
            placeholder="Min. 12 characters"
        )

        confirm_password = st.text_input(
            "Confirm New Password",
            type="password",
            placeholder="Re-enter new password"
        )

        if st.form_submit_button("Update Password"):
            if not current_password or not new_password:
                st.error("Please fill in all fields")
            elif new_password != confirm_password:
                st.error("New passwords do not match")
            elif len(new_password) < 12:
                st.error("Password must be at least 12 characters")
            else:
                success, msg = change_password(current_password, new_password)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    st.markdown("<hr style='border-color: #333; margin: 2rem 0;'>", unsafe_allow_html=True)

    # Logout section
    st.markdown("#### Session")

    col1, col2 = st.columns([3, 1])

    with col1:
        st.markdown("""
        <p style="color: #6b7280; font-size: 14px;">
            Sign out of your current session on this device.
        </p>
        """, unsafe_allow_html=True)

    with col2:
        if st.button("Sign Out", type="secondary", use_container_width=True):
            logout()
            st.rerun()

    # Danger zone
    st.markdown("<hr style='border-color: #333; margin: 2rem 0;'>", unsafe_allow_html=True)

    with st.expander("Danger Zone", expanded=False):
        st.markdown("""
        <p style="color: #ef4444; font-size: 14px;">
            These actions cannot be undone.
        </p>
        """, unsafe_allow_html=True)

        st.button("Delete Account", type="secondary", disabled=True,
                  help="Contact an administrator to delete your account")


# Render when loaded as a Streamlit multipage page
render_settings_page()
