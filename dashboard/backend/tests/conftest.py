"""
Shared test fixtures for the dashboard backend test suite.
"""

import json
import os
import sys
import tempfile

import pytest

# Add backend to path so we can import modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override env vars BEFORE importing any modules
os.environ["JWT_SECRET"] = "test-secret-key-not-for-production"
os.environ["USERS_FILE"] = ""  # Will be overridden per-test
os.environ["CONFIG_PATH"] = ""  # Will be overridden per-test
os.environ["CONFIG_BACKUP_DIR"] = ""  # Will be overridden per-test
os.environ["RUNNER_STATE_FILE"] = ""  # Will be overridden per-test


VALID_CONFIG_YAML = """
acquisition:
  keywords:
    - cancer
    - immunotherapy
  filters:
    max_per_keyword: 5000
    year_range: [2020, 2026]
  sources:
    - openalex
    - semantic_scholar

processing:
  chunking:
    max_chunk_size: 1500
    overlap: 200

embedding:
  model_name: nomic-embed-text
  collection_name: sme_papers_v2
  vector_size: 768
  remote_url: http://sme_ollama:11434
""".strip()


@pytest.fixture
def tmp_dir():
    """Provide a temp directory that auto-cleans."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def config_file(tmp_dir):
    """Create a temp config file with valid YAML."""
    path = os.path.join(tmp_dir, "config.yaml")
    with open(path, "w") as f:
        f.write(VALID_CONFIG_YAML)
    return path


@pytest.fixture
def users_file(tmp_dir):
    """Create a temp users file with test users (admin, operator, viewer)."""
    path = os.path.join(tmp_dir, "users.json")
    # Import here to use with overridden env
    from auth import pwd_context
    users = {
        "admin_user": {
            "username": "admin_user",
            "role": "admin",
            "hashed_password": pwd_context.hash("admin_pass"),
        },
        "operator_user": {
            "username": "operator_user",
            "role": "operator",
            "hashed_password": pwd_context.hash("operator_pass"),
        },
        "viewer_user": {
            "username": "viewer_user",
            "role": "viewer",
            "hashed_password": pwd_context.hash("viewer_pass"),
        },
    }
    with open(path, "w") as f:
        json.dump(users, f)
    return path


@pytest.fixture
def setup_config_env(config_file, tmp_dir):
    """Set up config manager env vars for testing."""
    import config_manager
    config_manager.CONFIG_PATH = config_file
    config_manager.BACKUP_DIR = os.path.join(tmp_dir, "backups")
    yield config_file


@pytest.fixture
def setup_auth_env(users_file):
    """Set up auth env vars for testing."""
    import auth
    auth.USERS_FILE = users_file
    auth.JWT_SECRET = "test-secret-key-not-for-production"
    yield users_file
