#!/usr/bin/env python3
"""
SME Research Assistant — Qdrant Benchmark & Diagnostics CLI

Usage:
    python -m src.indexing.benchmark status
    python -m src.indexing.benchmark optimize [--skip-gate]
    python -m src.indexing.benchmark canary
    python -m src.indexing.benchmark full [--queries N]
    python -m src.indexing.benchmark bm25-check

Requires:
    - Qdrant running (default localhost:6334)
    - Config file (config/config.yaml or config/docker_config.yaml)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Setup logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark")


def load_config() -> Dict:
    """Load application config from yaml."""
    import yaml

    for path in ["config/config.yaml", "config/docker_config.yaml"]:
        if Path(path).exists():
            with open(path) as f:
                cfg = yaml.safe_load(f)
            logger.info(f"[CONFIG] Loaded from {path}")
            return cfg
    logger.warning("[CONFIG] No config file found — using defaults")
    return {}


def get_qdrant_client(config: Dict):
    """Create a Qdrant client from config."""
    from qdrant_client import QdrantClient

    vs_cfg = config.get("vector_store", {})
    host = vs_cfg.get("host", "localhost")
    port = vs_cfg.get("port", 6334)
    client = QdrantClient(host=host, port=port)
    logger.info(f"[QDRANT] Connected to {host}:{port}")
    return client


def log_system_resources() -> Dict:
    """Log current system resource usage."""
    import psutil

    mem = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=0.5)

    resources = {
        "ram_total_gb":     round(mem.total / 1e9, 2),
        "ram_available_gb": round(mem.available / 1e9, 2),
        "ram_used_pct":     mem.percent,
        "cpu_percent":      cpu_pct,
    }

    # GPU check
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / 1e9
            reserved  = torch.cuda.memory_reserved(0) / 1e9
            total     = torch.cuda.get_device_properties(0).total_mem / 1e9
            resources["gpu_allocated_gb"] = round(allocated, 2)
            resources["gpu_reserved_gb"]  = round(reserved, 2)
            resources["gpu_total_gb"]     = round(total, 2)
    except Exception:
        pass

    logger.info(
        f"[RESOURCES] RAM: {resources['ram_available_gb']:.1f}/{resources['ram_total_gb']:.1f} GB "
        f"({resources['ram_used_pct']:.0f}% used) | CPU: {resources['cpu_percent']:.0f}%"
    )
    return resources


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────
def cmd_status(config: Dict):
    """Show collection status, index completeness, and resource usage."""
    from src.indexing.qdrant_optimizer import get_collection_info

    client = get_qdrant_client(config)
    coll_name = config.get("vector_store", {}).get("collection_name", "sme_papers")

    # System resources
    resources = log_system_resources()

    # Collection info
    info = get_collection_info(client, coll_name)

    total   = info.get("vector_count", 0)
    indexed = info.get("indexed_vectors_count", 0)
    completeness = (indexed / total * 100) if total > 0 else 100.0

    print("\n" + "=" * 60)
    print(f"  COLLECTION: {coll_name}")
    print("=" * 60)
    print(f"  Vectors:         {total:>10,}")
    print(f"  Indexed:         {indexed:>10,}")
    print(f"  Completeness:    {completeness:>9.1f}%")
    print(f"  Optimizer:       {info.get('optimizer_status', 'unknown')}")
    print()
    print(f"  RAM Available:   {resources['ram_available_gb']:>8.1f} GB")
    print(f"  RAM Used:        {resources['ram_used_pct']:>8.0f}%")
    print(f"  CPU:             {resources['cpu_percent']:>8.0f}%")
    if "gpu_total_gb" in resources:
        print(f"  GPU Total:       {resources['gpu_total_gb']:>8.1f} GB")
        print(f"  GPU Allocated:   {resources['gpu_allocated_gb']:>8.1f} GB")
    print("=" * 60)

    # Config details
    if info.get("config"):
        print("\n  Current Config:")
        for k, v in info["config"].items():
            print(f"    {k}: {v}")
        print()


def cmd_optimize(config: Dict, skip_gate: bool = False):
    """Run the full startup optimization."""
    from src.indexing.qdrant_optimizer import run_startup_optimization

    client = get_qdrant_client(config)
    coll_name = config.get("vector_store", {}).get("collection_name", "sme_papers")

    logger.info("[OPTIMIZE] Running full startup optimization...")
    result = run_startup_optimization(
        client=client,
        collection_name=coll_name,
        config=config,
        skip_index_gate=skip_gate,
    )

    print(f"\n  Tier:            {result['tier']}")
    print(f"  Config Match:    {'✅' if result['config_match'] else '⚠️  MISMATCH'}")
    print(f"  Index Ready:     {'✅' if result['index_ready'] else '❌ NOT READY'}")
    print(f"  Report:          {result['report_path']}")

    if result["config_deltas"]:
        print("\n  Config Mismatches:")
        for delta in result["config_deltas"]:
            print(f"    • {delta}")

    # Log resources after optimization
    log_system_resources()
    return result


def cmd_canary(config: Dict):
    """Run canary queries to verify search is working."""
    client = get_qdrant_client(config)
    coll_name = config.get("vector_store", {}).get("collection_name", "sme_papers")
    dim = config.get("embedding", {}).get("dimension", 4096)

    import random
    import numpy as np

    # Generate 3 random query vectors
    num_canaries = 3
    results_summary = []

    logger.info(f"[CANARY] Running {num_canaries} canary queries (dim={dim})...")

    for i in range(num_canaries):
        # Random unit vector
        vec = np.random.randn(dim).astype(np.float32)
        vec = (vec / np.linalg.norm(vec)).tolist()

        start = time.time()
        try:
            from qdrant_client.http import models
            results = client.query_points(
                collection_name=coll_name,
                query=vec,
                search_params=models.SearchParams(
                    hnsw_ef=400,
                    exact=False,
                    quantization=models.QuantizationSearchParams(
                        ignore=False,
                        rescore=True,
                        oversampling=2.0,
                    ),
                ),
                limit=10,
                with_payload=False,
            ).points
            latency_ms = (time.time() - start) * 1000
            scores = [r.score for r in results] if results else []

            results_summary.append({
                "query": i + 1,
                "latency_ms": round(latency_ms, 1),
                "results": len(results),
                "top_score": round(scores[0], 4) if scores else 0,
                "min_score": round(scores[-1], 4) if scores else 0,
                "status": "✅",
            })
            logger.info(
                f"[CANARY] Query {i+1}: {len(results)} results, "
                f"{latency_ms:.1f}ms, scores={scores[0]:.4f}..{scores[-1]:.4f}"
                if scores else f"[CANARY] Query {i+1}: 0 results, {latency_ms:.1f}ms"
            )

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            results_summary.append({
                "query": i + 1,
                "latency_ms": round(latency_ms, 1),
                "results": 0,
                "status": f"❌ {e}",
            })
            logger.error(f"[CANARY] Query {i+1} failed: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("  CANARY RESULTS")
    print("=" * 60)
    for r in results_summary:
        print(
            f"  Query {r['query']}: {r['status']}  "
            f"latency={r['latency_ms']:.0f}ms  results={r.get('results', 0)}"
        )

    latencies = [r["latency_ms"] for r in results_summary if "❌" not in str(r.get("status", ""))]
    if latencies:
        avg = sum(latencies) / len(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\n  Average: {avg:.0f}ms  P95: {p95:.0f}ms")
        if avg > 100:
            print("  ⚠️  Latency above 100ms — check index completeness!")
        else:
            print("  ✅ Latency within expected range")
    print("=" * 60)

    # Resources after queries
    log_system_resources()


def cmd_bm25_check(config: Dict):
    """Check BM25 index staleness against Qdrant."""
    from src.indexing.bm25_index import BM25Index

    client = get_qdrant_client(config)
    coll_name = config.get("vector_store", {}).get("collection_name", "sme_papers")
    bm25_cfg = config.get("bm25", {})
    index_path = bm25_cfg.get("index_path", "data/bm25_index.pkl")

    bm25 = BM25Index(index_path=index_path)
    loaded = bm25.load()

    # Get Qdrant point count
    try:
        info = client.get_collection(coll_name)
        qdrant_count = info.points_count or 0
    except Exception:
        qdrant_count = 0

    print("\n" + "=" * 60)
    print("  BM25 INDEX STATUS")
    print("=" * 60)
    print(f"  Index Path:     {index_path}")
    print(f"  Loaded:         {'✅' if loaded else '❌ Not found'}")
    print(f"  Chunks:         {bm25.count():,}")
    print(f"  Qdrant Points:  {qdrant_count:,}")

    if loaded:
        meta = bm25.get_metadata()
        print(f"  Build Time:     {meta.get('build_timestamp', 'unknown')}")
        stale = bm25.is_stale(qdrant_count)
        print(f"  Stale:          {'⚠️  YES — rebuild recommended' if stale else '✅ Fresh'}")
    else:
        print("  Stale:          ⚠️  No index exists — rebuild required")
    print("=" * 60)


def cmd_full_bench(config: Dict, num_queries: int = 10):
    """Run a full benchmark with multiple queries and resource monitoring."""
    import numpy as np

    client = get_qdrant_client(config)
    coll_name = config.get("vector_store", {}).get("collection_name", "sme_papers")
    dim = config.get("embedding", {}).get("dimension", 4096)

    logger.info(f"[FULL-BENCH] Running {num_queries} queries...")

    # Pre-check resources
    print("\n--- PRE-BENCHMARK RESOURCES ---")
    pre_resources = log_system_resources()

    from qdrant_client.http import models

    latencies = []
    for i in range(num_queries):
        vec = np.random.randn(dim).astype(np.float32)
        vec = (vec / np.linalg.norm(vec)).tolist()

        start = time.time()
        try:
            results = client.query_points(
                collection_name=coll_name,
                query=vec,
                search_params=models.SearchParams(
                    hnsw_ef=400,
                    exact=False,
                    quantization=models.QuantizationSearchParams(
                        ignore=False, rescore=True, oversampling=2.0,
                    ),
                ),
                limit=200,
                with_payload=False,
            ).points
            latency = (time.time() - start) * 1000
            latencies.append(latency)
            if (i + 1) % 5 == 0:
                logger.info(f"[FULL-BENCH] {i+1}/{num_queries} complete, last={latency:.1f}ms")
        except Exception as e:
            logger.error(f"[FULL-BENCH] Query {i+1} failed: {e}")

    # Post-check resources
    print("\n--- POST-BENCHMARK RESOURCES ---")
    post_resources = log_system_resources()

    # Statistics
    if latencies:
        latencies.sort()
        n = len(latencies)
        p50 = latencies[int(n * 0.5)]
        p95 = latencies[int(n * 0.95)]
        p99 = latencies[min(int(n * 0.99), n - 1)]
        avg = sum(latencies) / n

        ram_delta = pre_resources["ram_available_gb"] - post_resources["ram_available_gb"]

        print("\n" + "=" * 60)
        print("  FULL BENCHMARK RESULTS")
        print("=" * 60)
        print(f"  Queries:     {num_queries}")
        print(f"  Successful:  {n}")
        print(f"  P50:         {p50:.1f} ms")
        print(f"  P95:         {p95:.1f} ms")
        print(f"  P99:         {p99:.1f} ms")
        print(f"  Average:     {avg:.1f} ms")
        print(f"  RAM delta:   {ram_delta:+.2f} GB")
        print("=" * 60)

        if p95 > 100:
            print("  ⚠️  P95 > 100ms — investigate index completeness or config")
        elif p95 > 50:
            print("  ℹ️  P95 50-100ms — acceptable but monitor under load")
        else:
            print("  ✅ P95 < 50ms — excellent performance")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Qdrant Benchmark & Diagnostics CLI for SME Research Assistant"
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # status
    sub.add_parser("status", help="Show collection status & resources")

    # optimize
    opt_parser = sub.add_parser("optimize", help="Run startup optimization")
    opt_parser.add_argument("--skip-gate", action="store_true",
                            help="Skip index readiness gate (testing only)")

    # canary
    sub.add_parser("canary", help="Run canary queries")

    # full
    full_parser = sub.add_parser("full", help="Full benchmark")
    full_parser.add_argument("--queries", type=int, default=10, help="Number of queries")

    # bm25-check
    sub.add_parser("bm25-check", help="Check BM25 index staleness")

    args = parser.parse_args()
    config = load_config()

    if args.command == "status":
        cmd_status(config)
    elif args.command == "optimize":
        cmd_optimize(config, skip_gate=args.skip_gate)
    elif args.command == "canary":
        cmd_canary(config)
    elif args.command == "full":
        cmd_full_bench(config, num_queries=args.queries)
    elif args.command == "bm25-check":
        cmd_bm25_check(config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
