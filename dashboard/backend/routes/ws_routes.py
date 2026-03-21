"""WebSocket route: real-time metrics, logs, events."""
import asyncio
import subprocess
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("dashboard.ws")
router = APIRouter()

# Import shared ws_manager from main — we'll use a module-level ref
# set by main.py at startup (avoids circular imports)
_ws_manager = None


def set_ws_manager(manager):
    global _ws_manager
    _ws_manager = manager


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Main WebSocket endpoint.
    After connect, pushes: metrics.update (1s), log.line (real-time), counts (2s).
    Client can send: log.filter, log.pause.
    """
    if _ws_manager is None:
        await ws.close(code=1011, reason="Server not ready")
        return

    await _ws_manager.connect(ws)

    # Start log tailing in background
    log_task = asyncio.create_task(_stream_logs(ws))

    try:
        while True:
            # Receive client messages (filter, pause, etc.)
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "log.filter":
                # Store filter preferences for this connection
                ws._log_filter = data.get("payload", {})
            elif msg_type == "log.pause":
                ws._log_paused = data.get("payload", {}).get("paused", False)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[WS] Error: {e}")
    finally:
        log_task.cancel()
        await _ws_manager.disconnect(ws)


async def _stream_logs(ws: WebSocket):
    """Tail the pipeline log file and stream to this client."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "sme_app", "tail", "-f", "-n", "100",
            "/app/data/autonomous_update.log",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async for line_bytes in proc.stdout:
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            # Check if client paused
            if getattr(ws, "_log_paused", False):
                continue

            parsed = _parse_log_line(line)

            # Apply client filters
            log_filter = getattr(ws, "_log_filter", {})
            if log_filter:
                levels = log_filter.get("levels", [])
                if levels and parsed.get("level") not in levels:
                    continue
                stages = log_filter.get("stages", [])
                if stages and parsed.get("stage") not in stages:
                    continue
                search = log_filter.get("search", "")
                if search and search.lower() not in line.lower():
                    continue

            try:
                await ws.send_json({"type": "log.line", "payload": parsed})
            except Exception:
                break

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f"[WS] Log stream ended: {e}")


def _parse_log_line(line: str) -> dict:
    """Parse a log line into structured format."""
    # Format: 2026-03-01 13:20:54,051 - INFO - [EMBED-OK] Paper=doi:...
    parts = line.split(" - ", 2)
    if len(parts) >= 3:
        ts = parts[0].strip()
        level = parts[1].strip()
        msg = parts[2].strip()

        # Extract stage tag like [EMBED-OK]
        stage = ""
        if msg.startswith("[") and "]" in msg:
            stage = msg[1 : msg.index("]")]
            
        # --- Added: High-speed telemetry detection ---
        from db_reader import increment_count
        if "[CHUNK-COMPLETE]" in msg:
            increment_count("chunked")
        elif "✅ Stored Paper" in msg:
            increment_count("embedded")

        return {"ts": ts, "level": level, "stage": stage, "msg": msg}

    return {"ts": "", "level": "INFO", "stage": "", "msg": line}
