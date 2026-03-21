"""
Unit tests for auth.py — JWT tokens, RBAC, user management.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestUserManagement:
    """Tests for user creation and authentication."""

    def test_create_user(self, setup_auth_env):
        from auth import create_user, _load_users
        create_user("newuser", "pass123", "viewer")
        users = _load_users()
        assert "newuser" in users
        assert users["newuser"]["role"] == "viewer"

    def test_create_duplicate_user_fails(self, setup_auth_env):
        import pytest
        from auth import create_user
        with pytest.raises(ValueError, match="already exists"):
            create_user("admin_user", "new_pass", "admin")

    def test_create_user_invalid_role(self, setup_auth_env):
        import pytest
        from auth import create_user
        with pytest.raises(ValueError, match="Invalid role"):
            create_user("bad_role_user", "pass", "superadmin")

    def test_authenticate_valid(self, setup_auth_env):
        from auth import authenticate_user
        user = authenticate_user("admin_user", "admin_pass")
        assert user is not None
        assert user["role"] == "admin"

    def test_authenticate_wrong_password(self, setup_auth_env):
        from auth import authenticate_user
        user = authenticate_user("admin_user", "wrong_password")
        assert user is None

    def test_authenticate_nonexistent_user(self, setup_auth_env):
        from auth import authenticate_user
        user = authenticate_user("nobody", "pass")
        assert user is None


class TestTokens:
    """Tests for JWT token creation and decoding."""

    def test_create_and_decode_access_token(self, setup_auth_env):
        from auth import create_access_token, decode_token
        token = create_access_token("admin_user", "admin")
        payload = decode_token(token)
        assert payload.sub == "admin_user"
        assert payload.role == "admin"

    def test_create_and_decode_refresh_token(self, setup_auth_env):
        from auth import create_refresh_token, decode_token
        token = create_refresh_token("operator_user", "operator")
        payload = decode_token(token)
        assert payload.sub == "operator_user"
        assert payload.role == "operator"

    def test_token_expiration_included(self, setup_auth_env):
        from auth import create_access_token, decode_token
        token = create_access_token("viewer_user", "viewer")
        payload = decode_token(token)
        assert payload.exp > time.time()

    def test_invalid_token_rejected(self, setup_auth_env):
        import pytest
        from fastapi import HTTPException
        from auth import decode_token
        with pytest.raises(HTTPException) as exc_info:
            decode_token("not.a.real.token")
        assert exc_info.value.status_code == 401

    def test_tampered_token_rejected(self, setup_auth_env):
        import pytest
        from fastapi import HTTPException
        from auth import create_access_token, decode_token
        token = create_access_token("admin_user", "admin")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(HTTPException) as exc_info:
            decode_token(tampered)
        assert exc_info.value.status_code == 401


class TestRBAC:
    """Tests for role hierarchy and access control."""

    def test_role_hierarchy_values(self):
        from auth import ROLE_HIERARCHY
        assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["operator"]
        assert ROLE_HIERARCHY["operator"] > ROLE_HIERARCHY["viewer"]

    def test_admin_has_highest_privilege(self):
        from auth import ROLE_HIERARCHY
        assert ROLE_HIERARCHY["admin"] == max(ROLE_HIERARCHY.values())

    def test_password_hashing(self, setup_auth_env):
        from auth import pwd_context
        hashed = pwd_context.hash("testpassword")
        assert hashed != "testpassword"
        assert pwd_context.verify("testpassword", hashed)
        assert not pwd_context.verify("wrongpassword", hashed)
