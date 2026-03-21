"""
SME Dashboard — Pipeline Command Runner

HTTP client bridging to the internal pipeline API within sme_app container.
Replaces legacy docker exec execution layer.
"""

import httpx
import logging
import psutil
from typing import Optional

from audit_logger import log_audit

logger = logging.getLogger("dashboard.runner")

API_URL = "http://sme_app:8000"

class PipelineProcessTracker:
    """
    Communicates with the internal pipeline API hosted on sme_app:8000.
    """

    def get_status(self) -> dict:
        """Return current pipeline status from the internal API."""
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{API_URL}/status")
            if resp.status_code == 200:
                return resp.json()
            return {"running": False, "uptime_sec": 0, "error": f"API HTTP {resp.status_code}"}
        except Exception as e:
            logger.debug(f"[RUNNER] API get_status failed: {e}")
            return {"running": False, "uptime_sec": 0, "error": "Internal API unreachable"}

    def start(self, mode: str, user_id: str) -> dict:
        """Issue an HTTP start command to the internal API."""
        log_audit(user_id, "pipeline.start_request", {"mode": mode})
        logger.info(f"[RUNNER] Requesting pipeline start: {mode} (by {user_id})")
        
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(f"{API_URL}/start", json={"mode": mode, "user_id": user_id})
                
            if resp.status_code == 200:
                data = resp.json()
                log_audit(user_id, "pipeline.start_success", {"mode": mode, "pid": data.get("pid")})
                logger.info(f"[RUNNER] Pipeline started successfully: {data}")
                return data
                
            error_msg = resp.json().get("detail", resp.text)
            raise RuntimeError(f"API Start failed: {error_msg}")
            
        except httpx.RequestError as e:
            raise RuntimeError(f"Pipeline API unreachable: {e}")

    def stop(self, force: bool, user_id: str) -> dict:
        """Issue an HTTP stop command to the internal API."""
        log_audit(user_id, "pipeline.stop_request", {"force": force})
        logger.info(f"[RUNNER] Requesting pipeline stop: force={force} (by {user_id})")
        
        try:
            # high timeout because graceful stop could take 30s
            with httpx.Client(timeout=35.0) as client:
                resp = client.post(f"{API_URL}/stop", json={"force": force, "user_id": user_id})
                
            if resp.status_code == 200:
                data = resp.json()
                log_audit(user_id, "pipeline.stop_success", {"force": force, "signal": data.get("signal")})
                logger.info(f"[RUNNER] Pipeline stopped successfully: {data}")
                return data
                
            error_msg = resp.json().get("detail", resp.text)
            raise RuntimeError(f"API Stop failed: {error_msg}")
            
        except httpx.RequestError as e:
            raise RuntimeError(f"Pipeline API unreachable: {e}")

    def run_precheck(self) -> list[dict]:
        """Run pre-flight checks before starting the pipeline."""
        checks = []

        # 1. Container internal API reachable
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{API_URL}/status")
            status = "pass" if resp.status_code == 200 else "fail"
            checks.append({"name": "Internal Pipeline API", "status": status, 
                           "detail": f"HTTP {resp.status_code}"})
        except Exception as e:
            checks.append({"name": "Internal Pipeline API", "status": "fail", "detail": "Unreachable"})

        # 2. Config valid
        try:
            from config_manager import read_config, validate_config
            cfg = read_config()
            result = validate_config(cfg["yaml"])
            checks.append({"name": "Config valid", "status": "pass" if result["valid"] else "fail",
                           "detail": str(result.get("errors", []))[:200]})
        except Exception as e:
            checks.append({"name": "Config valid", "status": "fail", "detail": str(e)})

        # 3. Qdrant reachable
        try:
            resp = httpx.get(f"http://sme_qdrant:6333/collections", timeout=5)
            checks.append({"name": "Qdrant reachable", "status": "pass" if resp.status_code == 200 else "fail",
                           "detail": f"HTTP {resp.status_code}"})
        except Exception as e:
            checks.append({"name": "Qdrant reachable", "status": "fail", "detail": str(e)})

        # 4. Keywords configured
        try:
            import sys
            sys.path.insert(0, "/app")
            from src.utils.helpers import load_config

            config = load_config("/app/config/acquisition_config.yaml")
            keywords = config.get("acquisition", {}).get("keywords", [])

            if keywords and len(keywords) > 0:
                checks.append({"name": "Keywords configured", "status": "pass",
                              "detail": f"{len(keywords)} keywords found"})
            else:
                checks.append({"name": "Keywords configured", "status": "fail",
                              "detail": "No keywords configured in acquisition_config.yaml"})
        except Exception as e:
            checks.append({"name": "Keywords configured", "status": "fail", "detail": str(e)})

        # 5. Disk free space (check data volume)
        try:
            disk = psutil.disk_usage("/data")
            free_gb = disk.free / 1e9
            status = "pass" if free_gb > 10 else "warn" if free_gb > 5 else "fail"
            checks.append({"name": "Disk free space (/data)", "status": status, "detail": f"{free_gb:.1f} GB free"})
        except Exception as e:
            checks.append({"name": "Disk free space (/data)", "status": "fail", "detail": str(e)})

        return checks


# Singleton
tracker = PipelineProcessTracker()
