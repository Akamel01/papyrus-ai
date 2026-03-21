"""
Unit tests for config_manager.py — validation, save, backup, revert.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import VALID_CONFIG_YAML


class TestValidation:
    """Tests for validate_config()."""

    def test_valid_config(self):
        from config_manager import validate_config
        result = validate_config(VALID_CONFIG_YAML)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_invalid_yaml_syntax(self):
        from config_manager import validate_config
        bad_yaml = "key: [unclosed bracket"
        result = validate_config(bad_yaml)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "unclosed" in result["errors"][0]["msg"].lower() or result["errors"][0]["line"] > 0

    def test_non_mapping_yaml(self):
        from config_manager import validate_config
        result = validate_config("- just\n- a\n- list")
        assert result["valid"] is False
        assert any("mapping" in e["msg"].lower() for e in result["errors"])

    def test_missing_required_section(self):
        from config_manager import validate_config
        yaml_missing = """
acquisition:
  keywords: [cancer]
processing:
  chunking:
    max_chunk_size: 1500
# Missing embedding section
"""
        result = validate_config(yaml_missing)
        assert result["valid"] is False
        assert any("embedding" in e["msg"] for e in result["errors"])

    def test_empty_keywords(self):
        from config_manager import validate_config
        yaml_text = """
acquisition:
  keywords: []
processing:
  chunking: {}
embedding:
  model_name: nomic
  collection_name: test
"""
        result = validate_config(yaml_text)
        assert result["valid"] is False
        assert any("keywords" in e["msg"] for e in result["errors"])

    def test_missing_model_name(self):
        from config_manager import validate_config
        yaml_text = """
acquisition:
  keywords: [test]
processing:
  chunking: {}
embedding:
  collection_name: test
"""
        result = validate_config(yaml_text)
        assert result["valid"] is False
        assert any("model_name" in e["msg"] for e in result["errors"])

    def test_high_max_per_keyword_warning(self):
        from config_manager import validate_config
        yaml_text = """
acquisition:
  keywords: [cancer]
  filters:
    max_per_keyword: 500000
processing:
  chunking: {}
embedding:
  model_name: nomic
  collection_name: test
"""
        result = validate_config(yaml_text)
        assert result["valid"] is True
        assert len(result["warnings"]) > 0
        assert any("high" in w["msg"].lower() for w in result["warnings"])

    def test_forbidden_yaml_tag_python(self):
        from config_manager import validate_config
        result = validate_config("key: !!python/object/apply:os.system ['rm -rf /']")
        assert result["valid"] is False
        assert any("Forbidden" in e["msg"] for e in result["errors"])

    def test_forbidden_yaml_tag_exec(self):
        from config_manager import validate_config
        result = validate_config("key: !!exec 'malicious'")
        assert result["valid"] is False

    def test_forbidden_yaml_tag_ruby(self):
        from config_manager import validate_config
        result = validate_config("key: !!ruby/object:Gem 'x'")
        assert result["valid"] is False


class TestETag:
    """Tests for ETag computation."""

    def test_etag_deterministic(self):
        from config_manager import compute_etag
        etag1 = compute_etag("hello world")
        etag2 = compute_etag("hello world")
        assert etag1 == etag2

    def test_etag_changes_with_content(self):
        from config_manager import compute_etag
        etag1 = compute_etag("hello")
        etag2 = compute_etag("world")
        assert etag1 != etag2

    def test_etag_format(self):
        from config_manager import compute_etag
        etag = compute_etag("test")
        assert etag.startswith("sha256:")
        assert len(etag) == len("sha256:") + 16  # 16 hex chars


class TestSaveAndBackup:
    """Tests for save_config with atomic write + backup."""

    def test_save_creates_backup(self, setup_config_env, tmp_dir):
        import config_manager
        new_yaml = VALID_CONFIG_YAML.replace("cancer", "diabetes")
        current = config_manager.read_config()

        result = config_manager.save_config(new_yaml, current["etag"], "test_user")
        assert result["ok"] is True
        assert result["backup_path"].endswith(".yaml")
        assert "test_user" in result["backup_path"]

        # Verify backup exists
        backup_dir = os.path.join(tmp_dir, "backups")
        backups = os.listdir(backup_dir)
        assert len(backups) == 1

    def test_save_updates_file(self, setup_config_env):
        import config_manager
        new_yaml = VALID_CONFIG_YAML.replace("cancer", "diabetes")
        current = config_manager.read_config()
        config_manager.save_config(new_yaml, current["etag"], "test_user")

        updated = config_manager.read_config()
        assert "diabetes" in updated["yaml"]
        assert "cancer" not in updated["yaml"]

    def test_save_etag_mismatch_rejected(self, setup_config_env):
        import config_manager
        import pytest
        with pytest.raises(ValueError, match="modified by another"):
            config_manager.save_config(VALID_CONFIG_YAML, "sha256:wrong_etag_here", "user")

    def test_save_invalid_yaml_rejected(self, setup_config_env):
        import config_manager
        import pytest
        current = config_manager.read_config()
        bad_yaml = "not: a: valid: [config"
        with pytest.raises(ValueError, match="Validation failed"):
            config_manager.save_config(bad_yaml, current["etag"], "user")

    def test_backup_secrets_scrubbed(self, setup_config_env, tmp_dir):
        import config_manager
        # First save: put api_key into the live config
        yaml_with_key = VALID_CONFIG_YAML + "\napis:\n  openalex:\n    api_key: my_secret_key_123"
        current = config_manager.read_config()
        config_manager.save_config(yaml_with_key, current["etag"], "admin")

        # Second save: backup now contains the api_key version
        current2 = config_manager.read_config()
        config_manager.save_config(yaml_with_key.replace("123", "456"), current2["etag"], "admin2")

        backup_dir = os.path.join(tmp_dir, "backups")
        # Get the second backup (which backed up the api_key version)
        backups = sorted(os.listdir(backup_dir))
        assert len(backups) == 2
        second_backup = backups[1]
        with open(os.path.join(backup_dir, second_backup)) as f:
            backup_content = f.read()
        assert "my_secret_key_123" not in backup_content
        assert "REDACTED" in backup_content

    def test_backup_pruning(self, setup_config_env, tmp_dir):
        import config_manager
        config_manager.MAX_BACKUPS = 3

        # Create 5 saves
        for i in range(5):
            current = config_manager.read_config()
            new_yaml = VALID_CONFIG_YAML.replace("5000", str(5000 + i))
            config_manager.save_config(new_yaml, current["etag"], f"user_{i}")

        backup_dir = os.path.join(tmp_dir, "backups")
        backups = os.listdir(backup_dir)
        assert len(backups) <= 3

        # Reset
        config_manager.MAX_BACKUPS = 30


class TestListVersions:
    """Tests for list_versions()."""

    def test_empty_when_no_backups(self, setup_config_env, tmp_dir):
        import config_manager
        versions = config_manager.list_versions()
        assert versions == []

    def test_lists_backups_after_save(self, setup_config_env, tmp_dir):
        import config_manager
        current = config_manager.read_config()
        new_yaml = VALID_CONFIG_YAML.replace("cancer", "diabetes")
        config_manager.save_config(new_yaml, current["etag"], "admin")

        versions = config_manager.list_versions()
        assert len(versions) == 1
        assert versions[0]["user"] == "admin"
