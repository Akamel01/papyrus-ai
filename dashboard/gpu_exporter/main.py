import subprocess
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/metrics")
def get_gpu_metrics():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return JSONResponse(status_code=500, content={"error": "nvidia-smi failed"})

        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) >= 4:
            return {
                "vram_used_mb": float(parts[0]),
                "vram_total_mb": float(parts[1]),
                "util_pct": float(parts[2]),
                "temp_c": float(parts[3]),
            }
        return JSONResponse(status_code=500, content={"error": "unexpected nvidia-smi output format"})
    except FileNotFoundError:
        return JSONResponse(status_code=500, content={"error": "nvidia-smi not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/health")
def health():
    return {"status": "ok"}
