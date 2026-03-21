"""
Unit tests for Live Monitoring Callback System.
Tests the callback functionality in monitoring.py and sequential_rag.py.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add project root to path (parent of tests/)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.monitoring import RunContext, StepTracker, start_run, end_run


class TestLiveMonitoringCallbacks(unittest.TestCase):
    """Test the callback system for live monitoring."""
    
    def setUp(self):
        """Reset context before each test."""
        # Clear any existing context
        from src.utils.monitoring import _run_context
        _run_context.set(None)
    
    def test_callback_registered_and_invoked(self):
        """Test that a registered callback is invoked when steps complete."""
        received_steps = []
        
        def mock_callback(step_data):
            received_steps.append(step_data)
        
        # Start run and register callback
        ctx = start_run("Test query", {"depth": "Medium"})
        ctx.set_callback(mock_callback)
        
        # Simulate a step completing
        with StepTracker("Test Step"):
            pass  # No actual work
        
        # Verify callback was invoked
        self.assertEqual(len(received_steps), 1)
        self.assertEqual(received_steps[0]["name"], "Test Step")
        self.assertEqual(received_steps[0]["status"], "success")
        self.assertIn("duration_seconds", received_steps[0])
    
    def test_no_callback_no_error(self):
        """Test that no callback is fine (graceful no-op)."""
        ctx = start_run("Test query", {})
        # No callback registered
        
        # This should not raise any errors
        with StepTracker("Test Step"):
            pass
        
        # Verify step was still logged
        self.assertEqual(len(ctx.steps), 1)
    
    def test_callback_error_handled_gracefully(self):
        """Test that a callback exception doesn't break the pipeline."""
        def bad_callback(step_data):
            raise ValueError("Simulated callback error")
        
        ctx = start_run("Test query", {})
        ctx.set_callback(bad_callback)
        
        # This should not raise, even though callback fails
        with StepTracker("Test Step"):
            pass
        
        # Verify step was still logged (fail-safe)
        self.assertEqual(len(ctx.steps), 1)
    
    def test_multiple_steps_all_received(self):
        """Test that multiple steps all invoke the callback."""
        received_steps = []
        
        def mock_callback(step_data):
            received_steps.append(step_data)
        
        ctx = start_run("Test query", {})
        ctx.set_callback(mock_callback)
        
        # Simulate multiple steps
        with StepTracker("Step 1"):
            pass
        with StepTracker("Step 2"):
            pass
        with StepTracker("Step 3"):
            pass
        
        # Verify all callbacks received
        self.assertEqual(len(received_steps), 3)
        self.assertEqual([s["name"] for s in received_steps], ["Step 1", "Step 2", "Step 3"])


if __name__ == "__main__":
    unittest.main()
