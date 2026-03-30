"""
SME Research Assistant - Streamlit Auth Helper

Handles JWT authentication with the auth service.
"""
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

import streamlit as st
import httpx

# Auth service URL (internal Docker network)
AUTH_SERVICE_URL = "http://auth:8000"


@dataclass
class AuthUser:
    """Authenticated user data."""
    id: str
    email: str
    display_name: Optional[str]
    role: str


def init_auth_state():
    """Initialize authentication state in session."""
    if "auth" not in st.session_state:
        st.session_state.auth = {
            "access_token": None,
            "refresh_token": None,
            "expires_at": 0,
            "user": None,
        }
        # Try to restore from localStorage on first load
        _try_restore_from_storage()


def _try_restore_from_storage():
    """Try to restore auth tokens from browser localStorage via query params."""
    # Check if we have a token in query params (set by JavaScript on page load)
    try:
        params = st.query_params
        stored_refresh = params.get("_auth_refresh")
        if stored_refresh:
            # Clear the query param to avoid URL pollution
            st.query_params.clear()
            # Try to refresh using the stored token
            st.session_state.auth["refresh_token"] = stored_refresh
            if refresh_tokens():
                return True
    except Exception:
        pass
    return False


def _save_to_storage():
    """Inject JavaScript to save auth tokens to localStorage."""
    if st.session_state.auth.get("refresh_token"):
        # Save refresh token to localStorage via JavaScript
        refresh_token = st.session_state.auth["refresh_token"]
        st.markdown(f'''
        <script>
            localStorage.setItem('sme_refresh_token', '{refresh_token}');
        </script>
        ''', unsafe_allow_html=True)


def _clear_storage():
    """Inject JavaScript to clear auth tokens from localStorage."""
    st.markdown('''
    <script>
        localStorage.removeItem('sme_refresh_token');
    </script>
    ''', unsafe_allow_html=True)


def is_authenticated() -> bool:
    """Check if user is currently authenticated."""
    init_auth_state()
    auth = st.session_state.auth

    if not auth["access_token"]:
        return False

    # Check if token is expired (with 30s buffer)
    if time.time() >= auth["expires_at"] - 30:
        # Try to refresh
        if auth["refresh_token"]:
            return refresh_tokens()
        return False

    return True


def get_current_user() -> Optional[AuthUser]:
    """Get current authenticated user."""
    init_auth_state()
    if not is_authenticated():
        return None

    user_data = st.session_state.auth["user"]
    if not user_data:
        return None

    # Defensive: ensure user_data is a dict (not already an AuthUser)
    if isinstance(user_data, AuthUser):
        return user_data

    # Handle dict-like access with proper error handling
    try:
        auth_user = AuthUser(
            id=user_data.get("id", ""),
            email=user_data.get("email", ""),
            display_name=user_data.get("display_name"),
            role=user_data.get("role", "user")
        )
        # Cache the AuthUser back to session state to avoid repeated conversions
        # This ensures isinstance check works on subsequent calls
        st.session_state.auth["user"] = auth_user
        return auth_user
    except (TypeError, AttributeError) as e:
        # If user_data is not dict-like, clear it and return None
        st.session_state.auth["user"] = None
        return None


def get_access_token() -> Optional[str]:
    """Get current access token if authenticated."""
    if not is_authenticated():
        return None
    return st.session_state.auth["access_token"]


def login(identifier: str, password: str) -> tuple[bool, str]:
    """
    Login with username/email and password.

    Args:
        identifier: Username or email address
        password: User's password

    Returns:
        (success, message) tuple
    """
    init_auth_state()

    try:
        with httpx.Client(timeout=10.0) as client:
            # Use 'email' field for compatibility but it accepts username too
            response = client.post(
                f"{AUTH_SERVICE_URL}/api/auth/login",
                json={"email": identifier, "password": password}
            )

            if response.status_code == 200:
                data = response.json()
                _store_tokens(data)

                # Fetch user info
                _fetch_user_info()

                # Persist to localStorage for session recovery
                _save_to_storage()

                return True, "Login successful"

            elif response.status_code == 400:
                error = response.json().get("detail", "Invalid input")
                return False, error

            elif response.status_code == 401:
                return False, "Invalid username/email or password"

            elif response.status_code == 403:
                return False, "Account is disabled"

            else:
                error = response.json().get("detail", "Login failed")
                return False, error

    except httpx.ConnectError:
        return False, "Cannot connect to auth service"
    except Exception as e:
        return False, f"Login error: {str(e)}"


def register(email: str, password: str, display_name: Optional[str] = None) -> tuple[bool, str]:
    """
    Register a new account.

    Returns:
        (success, message) tuple
    """
    init_auth_state()

    try:
        with httpx.Client(timeout=10.0) as client:
            payload = {"email": email, "password": password}
            if display_name:
                payload["display_name"] = display_name

            response = client.post(
                f"{AUTH_SERVICE_URL}/api/auth/register",
                json=payload
            )

            if response.status_code == 200:
                data = response.json()
                _store_tokens(data)

                # Fetch user info
                _fetch_user_info()

                return True, "Registration successful"

            elif response.status_code == 400:
                error = response.json().get("detail", "Registration failed")
                return False, error

            elif response.status_code == 422:
                # Validation error
                errors = response.json().get("detail", [])
                if isinstance(errors, list) and errors:
                    msg = errors[0].get("msg", "Validation error")
                    return False, msg
                return False, "Invalid input"

            else:
                error = response.json().get("detail", "Registration failed")
                return False, error

    except httpx.ConnectError:
        return False, "Cannot connect to auth service"
    except Exception as e:
        return False, f"Registration error: {str(e)}"


def logout():
    """Logout and clear session."""
    init_auth_state()

    token = st.session_state.auth.get("access_token")
    if token:
        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(
                    f"{AUTH_SERVICE_URL}/api/auth/logout",
                    headers={"Authorization": f"Bearer {token}"}
                )
        except Exception:
            pass  # Ignore errors, just clear local state

    # Clear localStorage tokens
    _clear_storage()

    # Clear auth state
    st.session_state.auth = {
        "access_token": None,
        "refresh_token": None,
        "expires_at": 0,
        "user": None,
    }


def refresh_tokens() -> bool:
    """Refresh the access token using refresh token."""
    init_auth_state()

    refresh_token = st.session_state.auth.get("refresh_token")
    if not refresh_token:
        return False

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{AUTH_SERVICE_URL}/api/auth/refresh",
                json={"refresh_token": refresh_token}
            )

            if response.status_code == 200:
                data = response.json()
                _store_tokens(data)
                return True
            else:
                # Refresh failed, clear auth
                logout()
                return False

    except Exception:
        return False


def _store_tokens(token_data: Dict[str, Any]):
    """Store tokens in session state."""
    init_auth_state()

    st.session_state.auth["access_token"] = token_data["access_token"]
    st.session_state.auth["refresh_token"] = token_data["refresh_token"]
    # expires_in is in seconds
    st.session_state.auth["expires_at"] = time.time() + token_data.get("expires_in", 900)


def _fetch_user_info():
    """Fetch current user info from auth service."""
    token = st.session_state.auth.get("access_token")
    if not token:
        return

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{AUTH_SERVICE_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                st.session_state.auth["user"] = response.json()
    except Exception:
        pass


# ─── API Key Management ───

def get_api_keys() -> list[Dict[str, Any]]:
    """Get user's API keys (masked)."""
    token = get_access_token()
    if not token:
        return []

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{AUTH_SERVICE_URL}/api/auth/me/keys",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    return []


def save_api_key(key_name: str, key_value: str) -> tuple[bool, str]:
    """Save an API key."""
    token = get_access_token()
    if not token:
        return False, "Not authenticated"

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.put(
                f"{AUTH_SERVICE_URL}/api/auth/me/keys",
                headers={"Authorization": f"Bearer {token}"},
                json={"key_name": key_name, "key_value": key_value}
            )

            if response.status_code == 200:
                return True, f"API key '{key_name}' saved"
            else:
                error = response.json().get("detail", "Failed to save key")
                return False, error

    except Exception as e:
        return False, str(e)


def delete_api_key(key_name: str) -> tuple[bool, str]:
    """Delete an API key."""
    token = get_access_token()
    if not token:
        return False, "Not authenticated"

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.delete(
                f"{AUTH_SERVICE_URL}/api/auth/me/keys/{key_name}",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                return True, f"API key '{key_name}' deleted"
            else:
                error = response.json().get("detail", "Failed to delete key")
                return False, error

    except Exception as e:
        return False, str(e)


# ─── User Preferences ───

def get_preferences() -> Dict[str, Any]:
    """Get user preferences."""
    token = get_access_token()
    if not token:
        return {}

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{AUTH_SERVICE_URL}/api/auth/me/preferences",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    return {}


def update_preferences(preferences: Dict[str, Any]) -> tuple[bool, str]:
    """Update user preferences."""
    token = get_access_token()
    if not token:
        return False, "Not authenticated"

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.put(
                f"{AUTH_SERVICE_URL}/api/auth/me/preferences",
                headers={"Authorization": f"Bearer {token}"},
                json=preferences
            )

            if response.status_code == 200:
                return True, "Preferences updated"
            else:
                error = response.json().get("detail", "Failed to update")
                return False, error

    except Exception as e:
        return False, str(e)


# ─── Password Change ───

def change_password(current_password: str, new_password: str) -> tuple[bool, str]:
    """Change user password."""
    token = get_access_token()
    if not token:
        return False, "Not authenticated"

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{AUTH_SERVICE_URL}/api/auth/me/password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": current_password,
                    "new_password": new_password
                }
            )

            if response.status_code == 200:
                return True, "Password changed successfully"
            else:
                error = response.json().get("detail", "Failed to change password")
                return False, error

    except Exception as e:
        return False, str(e)
