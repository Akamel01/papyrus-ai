"""
Internal API to control the SME pipeline process natively without Docker Exec.
Runs securely inside the sme_app container.
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
import psutil
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="SME Internal Pipeline API")
logger = logging.getLogger("pipeline_api")
logging.basicConfig(level=logging.INFO)

STATE_FILE = os.getenv("RUNNER_STATE_FILE", "/app/data/pipeline_state_internal.json")

# --- Whitelisted commands ---
ALLOWED_MODES = {
    "stream": ["python", "scripts/autonomous_update.py", "--stream"],
    "embed-only": ["python", "scripts/autonomous_update.py", "--stream", "--embed-only"],
    "test": ["python", "scripts/autonomous_update.py", "--stream", "--test"],
}

GRACEFUL_STOP_TIMEOUT = 30  # seconds

class PipelineProcessTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = self._load_state()
        self._proc: "Optional[subprocess.Popen]" = None

    def is_running(self) -> bool:
        """Check if autonomous_update.py is running by scanning /proc."""
        try:
            return self._scan_proc() is not None
        except Exception as e:
            logger.warning(f"is_running check failed: {e}")
            return False

    def _scan_proc(self) -> Optional[int]:
        target = "autonomous_update"
        for p in os.listdir("/proc"):
            if p.isdigit() and p != str(os.getpid()):
                try:
                    pid = int(p)
                    # Ignore child worker processes by checking process group leader
                    try:
                        if pid != os.getpgid(pid):
                            continue
                    except Exception:
                        pass

                    # Read as binary and decode - cmdline uses null bytes as separators
                    with open(f"/proc/{p}/cmdline", "rb") as f:
                        cmdline = f.read().decode("utf-8", errors="ignore")
                    # Replace null bytes with spaces for matching
                    cmdline = cmdline.replace("\x00", " ")
                    if target in cmdline and "python" in cmdline:
                        return pid
                except Exception:
                    continue
        return None

    def get_status(self) -> dict:
        running = self.is_running()
        state = self._state.copy()

        if running:
            if state.get("started_at"):
                state["uptime_sec"] = int(time.time() - state["started_at"])
            else:
                # Auto-detect uptime for processes started outside this API
                pid = self._scan_proc()
                if pid:
                    try:
                        p = psutil.Process(pid)
                        state["uptime_sec"] = int(time.time() - p.create_time())
                    except Exception:
                        state["uptime_sec"] = 0
                else:
                    state["uptime_sec"] = 0
        else:
            state["uptime_sec"] = 0

        state["running"] = running

        # Reconcile missing process
        if not running and state.get("pid"):
            # DO NOT clear state! If we clear state here, we sabotage the Auto-Restarter Watchdog!
            state["pid"] = None

        # Auto-detect unlogged process
        if running and not state.get("pid"):
            state["pid"] = self._scan_proc()
            state["mode"] = self._detect_mode()

        return state

    def start(self, mode: str, user_id: str) -> dict:
        if mode not in ALLOWED_MODES:
            raise ValueError(f"Invalid mode: {mode}")

        with self._lock:
            if self.is_running():
                raise RuntimeError("Pipeline already running")

            cmd = ALLOWED_MODES[mode]
            logger.info(f"Starting: {' '.join(cmd)} (by {user_id})")

            # Start process detached — redirect output to DEVNULL to prevent unbounded disk growth
            # The python process uses its own RotatingFileHandler for autonomous_update.log
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd="/app",
                start_new_session=True     # Creates new process group
            )
            
            self._proc = proc

            time.sleep(1.0)
            pid = self._scan_proc()
            if not pid and proc.poll() is not None:
                log_file.close()
                raise RuntimeError(
                    f"Process exited immediately (exit code {proc.returncode}). "
                    f"Check {log_path} for details."
                )

            self._state = {
                "pid": pid or proc.pid,
                "mode": mode,
                "started_at": time.time(),
                "started_by": user_id,
            }
            self._persist_state()
            return {"ok": True, "pid": self._state["pid"]}

    def stop(self, force: bool, user_id: str) -> dict:
        with self._lock:
            pid = self._scan_proc()
            if not pid:
                raise RuntimeError("No pipeline process running")

            sig_num = 9 if force else 15
            logger.info(f"Stopping entire process group for PID {pid} with signal {sig_num}")
            
            try:
                # Use killpg to kill the whole process group including spawned workers
                os.killpg(os.getpgid(pid), sig_num)
            except AttributeError:
                os.kill(pid, sig_num)
            except ProcessLookupError:
                pass
            
            if not force:
                for _ in range(GRACEFUL_STOP_TIMEOUT):
                    time.sleep(1)
                    if not self._scan_proc():
                        break
                else:
                    logger.warning("Graceful stop timed out, sending SIGKILL to process group")
                    try:
                        os.killpg(os.getpgid(pid), 9)
                    except AttributeError:
                        os.kill(pid, 9)
                    except ProcessLookupError:
                        pass
            
            # Reap the zombie using native Python wait
            try:
                if self._proc:
                    self._proc.wait(timeout=5.0)
                else:
                    os.waitpid(pid, 0)
            except Exception:
                pass
                        
            self._clear_state()
            self._proc = None
            return {"ok": True, "signal": "SIGKILL" if force else "SIGTERM"}

    def _detect_mode(self) -> Optional[str]:
        pid = self._scan_proc()
        if not pid:
            return None
        try:
            with open(f"/proc/{pid}/cmdline", "r") as f:
                cmdline = f.read()
            if "--test" in cmdline:
                return "test"
            elif "--embed-only" in cmdline:
                return "embed-only"
            elif "--stream" in cmdline:
                return "stream"
        except Exception:
            pass
        return None

    def _load_state(self) -> dict:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _persist_state(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self._state, f)

    def _clear_state(self):
        self._state = {}
        if os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except OSError:
                pass

tracker = PipelineProcessTracker()

# --- Circuit Breaker State ---
class CircuitBreaker:
    """Circuit breaker for pipeline watchdog with exponential backoff."""

    def __init__(self):
        self.state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failures: int = 0
        self.last_failure: Optional[float] = None
        self.opened_at: Optional[float] = None

        # Config
        self.failure_threshold: int = 5      # Open after 5 consecutive failures
        self.reset_timeout: int = 300        # Try again after 5 minutes
        self.stability_window: int = 60      # Require 60s uptime before resetting

    def calculate_backoff(self) -> float:
        """Exponential backoff: 10s, 20s, 40s, 80s, max 300s"""
        base_delay = 10
        max_delay = 300
        return min(base_delay * (2 ** max(0, self.failures - 1)), max_delay)

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = time.time()

    def should_open(self) -> bool:
        return self.failures >= self.failure_threshold

    def open_circuit(self) -> None:
        self.state = "OPEN"
        self.opened_at = time.time()

    def try_half_open(self) -> bool:
        """Check if circuit should transition to half-open. Returns True if transitioned."""
        if self.state != "OPEN" or self.opened_at is None:
            return False
        elapsed = time.time() - self.opened_at
        if elapsed > self.reset_timeout:
            self.state = "HALF_OPEN"
            return True
        return False

    def time_until_retry(self) -> float:
        """Returns seconds until circuit can retry (0 if not OPEN)."""
        if self.state != "OPEN" or self.opened_at is None:
            return 0
        elapsed = time.time() - self.opened_at
        return max(0, self.reset_timeout - elapsed)

    def reset(self) -> None:
        self.failures = 0
        self.state = "CLOSED"


circuit_breaker = CircuitBreaker()

class StartRequest(BaseModel):
    mode: str
    user_id: str

class StopRequest(BaseModel):
    force: bool
    user_id: str

import uvicorn

@app.on_event("startup")
async def startup_event():
    # Boot recovery & Watchdog
    state = tracker._load_state()

    async def pipeline_watchdog():
        """
        Monitor pipeline health with circuit breaker pattern.

        States:
        - CLOSED: Normal operation, restarts allowed
        - OPEN: Too many failures, no restarts for reset_timeout
        - HALF_OPEN: Testing if system recovered
        """
        cb = circuit_breaker  # Local reference for clarity

        logger.info("[WATCHDOG] Pipeline auto-restarter enabled with circuit breaker. Monitoring state...")
        last_running_ts: Optional[float] = None  # Track when we last saw the process running

        while True:
            await asyncio.sleep(10)
            try:
                current_state = tracker._load_state()

                # Skip if no mode configured (user hasn't started pipeline)
                if not current_state.get("mode"):
                    continue

                # Check circuit breaker state
                if cb.state == "OPEN":
                    if cb.try_half_open():
                        logger.info("[WATCHDOG] Circuit half-open, testing restart...")
                    else:
                        remaining = cb.time_until_retry()
                        logger.debug(f"[WATCHDOG] Circuit OPEN, {remaining:.0f}s until retry")
                        continue

                # Check if pipeline is running
                if tracker.is_running():
                    now = time.time()

                    # Track when process started running
                    if last_running_ts is None:
                        last_running_ts = now
                        continue  # Just started, wait for stability window

                    # Success - reset failure count after sustained uptime
                    if cb.failures > 0 and last_running_ts is not None:
                        uptime = now - last_running_ts
                        if uptime > cb.stability_window:
                            logger.info(f"[WATCHDOG] Pipeline stable for {uptime:.0f}s, resetting failures")
                            cb.reset()
                    continue

                # Pipeline not running - reset tracking
                last_running_ts = None

                # Handle restart with backoff and circuit breaker
                cb.record_failure()

                # Update state file with failure metadata
                current_state["restart_count"] = current_state.get("restart_count", 0) + 1
                current_state["last_error"] = "Process died unexpectedly"
                current_state["consecutive_failures"] = cb.failures
                current_state["circuit_breaker_state"] = cb.state
                tracker._state = current_state
                tracker._persist_state()

                # Check if we should open circuit
                if cb.should_open():
                    cb.open_circuit()
                    logger.error(
                        f"[WATCHDOG] Circuit OPEN: {cb.failures} consecutive failures. "
                        f"No restarts for {cb.reset_timeout}s"
                    )
                    continue

                # Calculate backoff delay
                backoff = cb.calculate_backoff()
                logger.warning(
                    f"[WATCHDOG] Pipeline died! Failure #{cb.failures}, "
                    f"waiting {backoff}s before restart..."
                )

                await asyncio.sleep(backoff)

                # Attempt restart
                try:
                    logger.info(f"[WATCHDOG] Attempting restart #{cb.failures}...")
                    tracker.start(current_state.get("mode", "stream"), "system_auto_recover")
                    last_running_ts = time.time()  # Start tracking uptime

                    if cb.state == "HALF_OPEN":
                        logger.info("[WATCHDOG] Half-open restart succeeded, monitoring for stability...")

                except Exception as e:
                    logger.error(f"[WATCHDOG] Restart failed: {e}")

            except Exception as e:
                logger.error(f"[WATCHDOG] Loop error: {e}")

    asyncio.create_task(pipeline_watchdog())

    if state.get("mode") and not tracker.is_running():
        logger.info("[STARTUP] Pipeline was running before crash. Auto-recovering...")
        try:
            tracker.start(state.get("mode", "stream"), "system_auto_recover")
        except Exception as e:
            logger.error(f"[STARTUP] Recovery failed: {e}")

@app.get("/status")
def status():
    return tracker.get_status()

@app.post("/start")
def start(req: StartRequest):
    try:
        return tracker.start(req.mode, req.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/stop")
def stop(req: StopRequest):
    try:
        return tracker.stop(req.force, req.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Log streaming endpoint ---

LOG_FILE = os.getenv("PIPELINE_LOG_FILE", "/app/data/autonomous_update.log")

@app.get("/logs")
async def stream_logs(tail: int = 100):
    """
    Stream log file contents. Initially returns last `tail` lines,
    then streams new lines as they appear (Server-Sent Events format).
    """
    async def generate():
        # First, send last N lines
        try:
            proc = await asyncio.create_subprocess_exec(
                "tail", "-n", str(tail), LOG_FILE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                yield f"data: {line}\n\n"
        except Exception as e:
            yield f"data: [LOG ERROR] {e}\n\n"

        # Then follow new lines
        try:
            proc = await asyncio.create_subprocess_exec(
                "tail", "-f", "-n", "0", LOG_FILE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            async for line_bytes in proc.stdout:
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    yield f"data: {line}\n\n"
        except asyncio.CancelledError:
            proc.terminate()
        except Exception as e:
            yield f"data: [LOG STREAM ERROR] {e}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/logs/recent")
async def get_recent_logs(lines: int = 100):
    """Get recent log lines as JSON array (non-streaming)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", str(min(lines, 1000)), LOG_FILE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"error": stderr.decode("utf-8", errors="replace"), "lines": []}

        log_lines = stdout.decode("utf-8", errors="replace").splitlines()
        return {"lines": log_lines, "count": len(log_lines)}
    except Exception as e:
        return {"error": str(e), "lines": []}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
