"""
Internal API to control the SME pipeline process natively without Docker Exec.
Runs securely inside the sme_app container.
"""

import json
import logging
import os
import subprocess
import threading
import time
import psutil
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="SME Internal Pipeline API")
logger = logging.getLogger("pipeline_api")
logging.basicConfig(level=logging.INFO)

STATE_FILE = os.getenv("RUNNER_STATE_FILE", "/data/pipeline_state_internal.json")

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
                    with open(f"/proc/{p}/cmdline", "r") as f:
                        cmdline = f.read()
                    if target in cmdline and cmdline.startswith("python"):
                        return int(p)
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
            self._clear_state()
            state["pid"] = None
            state["mode"] = None

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

            # Start process detached — capture stderr for diagnostics
            log_file = open("/data/pipeline_stdout.log", "a")
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.PIPE,
                cwd="/app",
                start_new_session=True
            )

            time.sleep(1.0)
            pid = self._scan_proc()
            if not pid and proc.poll() is not None:
                stderr_output = ""
                if proc.stderr:
                    stderr_output = proc.stderr.read(4096).decode(errors="replace")
                    proc.stderr.close()
                log_file.close()
                raise RuntimeError(
                    f"Process exited immediately (exit code {proc.returncode}). "
                    f"Stderr: {stderr_output or '(empty)'}"
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
            logger.info(f"Stopping PID {pid} with signal {sig_num}")
            
            try:
                os.kill(pid, sig_num)
            except ProcessLookupError:
                pass
            
            if not force:
                for _ in range(GRACEFUL_STOP_TIMEOUT):
                    time.sleep(1)
                    if not self._scan_proc():
                        break
                else:
                    logger.warning("Graceful stop timed out, sending SIGKILL")
                    try:
                        os.kill(pid, 9)
                    except ProcessLookupError:
                        pass
                        
            self._clear_state()
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

class StartRequest(BaseModel):
    mode: str
    user_id: str

class StopRequest(BaseModel):
    force: bool
    user_id: str

import uvicorn

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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
