"""
Unit tests for command_runner.py — whitelisted commands, injection prevention.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAllowedModes:
    """Tests for command whitelist."""

    def test_allowed_modes_exist(self):
        from command_runner import ALLOWED_MODES
        assert "stream" in ALLOWED_MODES
        assert "embed-only" in ALLOWED_MODES
        assert "test" in ALLOWED_MODES

    def test_only_three_modes(self):
        from command_runner import ALLOWED_MODES
        assert len(ALLOWED_MODES) == 3

    def test_all_commands_start_with_docker(self):
        from command_runner import ALLOWED_MODES
        for mode, cmd in ALLOWED_MODES.items():
            assert cmd[0] == "docker", f"Mode '{mode}' does not start with 'docker'"
            assert cmd[1] == "exec", f"Mode '{mode}' does not use 'exec'"

    def test_all_commands_use_detached_mode(self):
        from command_runner import ALLOWED_MODES
        for mode, cmd in ALLOWED_MODES.items():
            assert "-d" in cmd, f"Mode '{mode}' missing '-d' flag"

    def test_all_commands_target_sme_app(self):
        from command_runner import ALLOWED_MODES, CONTAINER_NAME
        for mode, cmd in ALLOWED_MODES.items():
            assert CONTAINER_NAME in cmd, f"Mode '{mode}' does not target {CONTAINER_NAME}"

    def test_stream_mode_has_stream_flag(self):
        from command_runner import ALLOWED_MODES
        cmd = ALLOWED_MODES["stream"]
        assert "--stream" in cmd

    def test_test_mode_has_test_flag(self):
        from command_runner import ALLOWED_MODES
        cmd = ALLOWED_MODES["test"]
        assert "--test" in cmd
        assert "--stream" in cmd

    def test_embed_only_has_embed_flag(self):
        from command_runner import ALLOWED_MODES
        cmd = ALLOWED_MODES["embed-only"]
        assert "--embed-only" in cmd
        assert "--stream" in cmd

    def test_no_shell_in_commands(self):
        """Ensure no shell metacharacters in whitelisted commands."""
        from command_runner import ALLOWED_MODES
        shell_chars = ["|", ";", "&", "`", "$", "(", ")", "{", "}"]
        for mode, cmd in ALLOWED_MODES.items():
            for part in cmd:
                for ch in shell_chars:
                    assert ch not in part, f"Shell char '{ch}' found in mode '{mode}': {part}"


class TestInjectionPrevention:
    """Tests that invalid modes are rejected at the whitelist level."""

    def test_invalid_mode_raises_value_error(self):
        from command_runner import PipelineProcessTracker
        import pytest
        tracker = PipelineProcessTracker()
        with pytest.raises(ValueError, match="Invalid mode"):
            tracker.start("stream; rm -rf /", "attacker")

    def test_mode_with_flag_injection_rejected(self):
        from command_runner import PipelineProcessTracker
        import pytest
        tracker = PipelineProcessTracker()
        with pytest.raises(ValueError):
            tracker.start("stream --extra-flag", "attacker")

    def test_empty_mode_rejected(self):
        from command_runner import PipelineProcessTracker
        import pytest
        tracker = PipelineProcessTracker()
        with pytest.raises(ValueError):
            tracker.start("", "attacker")

    def test_none_mode_raises(self):
        from command_runner import PipelineProcessTracker
        import pytest
        tracker = PipelineProcessTracker()
        with pytest.raises((ValueError, KeyError, TypeError)):
            tracker.start(None, "attacker")


class TestGracefulStopTimeout:
    """Tests for stop timeout configuration."""

    def test_graceful_stop_timeout_is_reasonable(self):
        from command_runner import GRACEFUL_STOP_TIMEOUT
        assert 10 <= GRACEFUL_STOP_TIMEOUT <= 60
