"""
Integration tests — test API endpoints via FastAPI TestClient.
Requires: test users, config file, auth tokens.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import VALID_CONFIG_YAML


@pytest.fixture
def client(setup_auth_env, setup_config_env):
    """Create a FastAPI TestClient with test env configured."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _login(client, username="admin_user", password="admin_pass"):
    """Helper: login and return auth headers."""
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuthEndpoints:
    """Tests for /api/auth/* endpoints."""

    def test_login_success(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin_user", "password": "admin_pass"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["role"] == "admin"

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin_user", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={"username": "nobody", "password": "pass"})
        assert resp.status_code == 401

    def test_me_endpoint(self, client):
        headers = _login(client)
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_me_without_auth_fails(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 403  # No credentials

    def test_token_refresh(self, client):
        login_resp = client.post("/api/auth/login", json={"username": "admin_user", "password": "admin_pass"})
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post(f"/api/auth/refresh?refresh_token={refresh_token}")
        assert resp.status_code == 200
        assert "access_token" in resp.json()


class TestConfigEndpoints:
    """Tests for /api/config/* endpoints."""

    def test_get_config(self, client):
        headers = _login(client)
        resp = client.get("/api/config", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "yaml" in data
        assert "etag" in data
        assert "acquisition" in data["yaml"]

    def test_validate_valid_config(self, client):
        headers = _login(client)
        resp = client.post("/api/config/validate", json={"yaml": VALID_CONFIG_YAML}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_validate_invalid_config(self, client):
        headers = _login(client)
        resp = client.post("/api/config/validate", json={"yaml": "not: [valid yaml"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_save_config_as_admin(self, client):
        headers = _login(client, "admin_user", "admin_pass")

        # Get current etag
        get_resp = client.get("/api/config", headers=headers)
        etag = get_resp.json()["etag"]

        # Save modified
        new_yaml = VALID_CONFIG_YAML.replace("5000", "6000")
        resp = client.post("/api/config/save", json={"yaml": new_yaml, "etag": etag}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_save_config_etag_mismatch(self, client):
        headers = _login(client)
        resp = client.post("/api/config/save", json={"yaml": VALID_CONFIG_YAML, "etag": "sha256:wrong"}, headers=headers)
        assert resp.status_code == 409  # Conflict

    def test_config_versions(self, client):
        headers = _login(client)
        resp = client.get("/api/config/versions", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestRBACEnforcement:
    """Tests that role restrictions are enforced across endpoints."""

    def test_viewer_cannot_save_config(self, client):
        headers = _login(client, "viewer_user", "viewer_pass")
        resp = client.post("/api/config/save", json={"yaml": VALID_CONFIG_YAML, "etag": "x"}, headers=headers)
        assert resp.status_code == 403

    def test_viewer_can_read_config(self, client):
        headers = _login(client, "viewer_user", "viewer_pass")
        resp = client.get("/api/config", headers=headers)
        assert resp.status_code == 200

    def test_viewer_can_validate_config(self, client):
        headers = _login(client, "viewer_user", "viewer_pass")
        resp = client.post("/api/config/validate", json={"yaml": VALID_CONFIG_YAML}, headers=headers)
        assert resp.status_code == 200

    def test_operator_cannot_save_config(self, client):
        headers = _login(client, "operator_user", "operator_pass")
        resp = client.post("/api/config/save", json={"yaml": VALID_CONFIG_YAML, "etag": "x"}, headers=headers)
        assert resp.status_code == 403

    def test_viewer_cannot_start_pipeline(self, client):
        headers = _login(client, "viewer_user", "viewer_pass")
        resp = client.post("/api/run/start", json={"mode": "test"}, headers=headers)
        assert resp.status_code == 403

    def test_viewer_cannot_stop_pipeline(self, client):
        headers = _login(client, "viewer_user", "viewer_pass")
        resp = client.post("/api/run/stop", json={"force": False}, headers=headers)
        assert resp.status_code == 403

    def test_viewer_cannot_access_audit(self, client):
        headers = _login(client, "viewer_user", "viewer_pass")
        resp = client.get("/api/audit", headers=headers)
        assert resp.status_code == 403

    def test_operator_cannot_access_audit(self, client):
        headers = _login(client, "operator_user", "operator_pass")
        resp = client.get("/api/audit", headers=headers)
        assert resp.status_code == 403

    def test_admin_can_access_audit(self, client):
        headers = _login(client)
        resp = client.get("/api/audit", headers=headers)
        assert resp.status_code == 200
