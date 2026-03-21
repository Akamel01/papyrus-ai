"""
SME Dashboard — System Metrics Collector

Collects CPU, RAM, Disk, GPU via psutil + nvidia-smi.
"""

import logging
import subprocess
from typing import Optional

import psutil

logger = logging.getLogger("dashboard.metrics")


class MetricsCollector:
    """Collects system metrics. Called every 1s from the broadcast loop."""

    async def collect(self) -> dict:
        data = {
            "cpu_pct": psutil.cpu_percent(interval=None),
            "ram_pct": psutil.virtual_memory().percent,
            "ram_used_mb": round(psutil.virtual_memory().used / 1e6),
            "ram_total_mb": round(psutil.virtual_memory().total / 1e6),
            "disk_free_gb": round(psutil.disk_usage("/data").free / 1e9, 1),
            "disk_total_gb": round(psutil.disk_usage("/data").total / 1e9, 1),
        }

        gpu = await self._collect_gpu()
        if gpu:
            data["gpu"] = gpu

        return data

    async def _collect_gpu(self) -> Optional[dict]:
        # Fetch GPU stats from the dedicated GPU exporter container
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://sme_gpu_exporter:8401/metrics")
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.debug(f"GPU metrics API returned {resp.status_code}")
                return None
        except Exception as e:
            logger.debug(f"GPU metrics unavailable (sme_gpu_exporter error): {e}")
            return None
