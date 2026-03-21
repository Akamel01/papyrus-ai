"""Quick smoke test for qdrant_optimizer functions (no Qdrant connection needed)."""

import sys
sys.path.insert(0, ".")

from src.indexing.qdrant_optimizer import (
    probe_hardware, 
    calculate_footprints,
    determine_tier,
    compute_optimal_params,
    validate_config,
    get_collection_info,
    wait_for_index_ready,
    generate_report,
    run_startup_optimization,
    log_vram_budget,
    TIERS,
)

print("=" * 60)
print("  QDRANT OPTIMIZER — FUNCTION SMOKE TESTS")
print("=" * 60)
print()

# 1. Imports
print("[1/6] All 11 exports imported OK ✅")

# 2. Hardware probing
hw = probe_hardware()
print(f"[2/6] Hardware: RAM={hw['total_ram_gb']}GB, CPU={hw['cpu_cores']} cores, "
      f"VRAM={hw.get('gpu_vram_gb', 'N/A')}GB ✅")

# 3. Footprint calculation
fp = calculate_footprints(vector_count=200000, dimension=4096, m=32)
print(f"[3/6] Footprints: raw={fp['raw_gb']:.2f}GB, "
      f"quant={fp['quantized_gb']:.2f}GB, "
      f"hnsw={fp['hnsw_gb']:.2f}GB, "
      f"total={fp['total_qdrant_gb']:.2f}GB ✅")

# 4. Tier selection
tier = determine_tier(fp, hw["available_ram_gb"])
print(f"[4/6] Tier for {hw['available_ram_gb']:.0f}GB free RAM: {tier} ✅")
assert tier in TIERS, f"Invalid tier: {tier}"

# 5. Optimal params
params = compute_optimal_params(
    dimension=4096, tier=tier, top_k_initial=200, cpu_cores=hw["cpu_cores"]
)
print(f"[5/6] Optimal params: m={params['m']}, ef_construct={params['ef_construct']}, "
      f"ef_search={params['ef_search']}, oversampling={params['oversampling']}, "
      f"on_disk={params['on_disk_vectors']}, quantization={params['use_quantization']} ✅")
assert 16 <= params["m"] <= 48, f"Unexpected m: {params['m']}"
assert params["ef_construct"] >= 64, f"ef_construct too low: {params['ef_construct']}"
assert params["ef_search"] >= 128, f"ef_search too low: {params['ef_search']}"

# 6. VRAM budget
gpu_vram = hw.get("gpu_vram_gb", 0)
if gpu_vram > 0:
    log_vram_budget(gpu_vram)
    print(f"[6/6] VRAM budget logged for {gpu_vram:.1f}GB ✅")
else:
    print(f"[6/6] No GPU detected — VRAM budget skipped ℹ️")

print()
print("=" * 60)
print("  ALL FUNCTION TESTS PASSED ✅")
print("=" * 60)


# Also test BM25 lifecycle functions
print()
print("=" * 60)
print("  BM25 LIFECYCLE — FUNCTION SMOKE TESTS")
print("=" * 60)

from src.indexing.bm25_index import BM25Index, BM25_STALENESS_THRESHOLD

bm25 = BM25Index(index_path="data/bm25_index.pkl")

# Test staleness detection (no metadata scenario)
stale = bm25.is_stale(qdrant_point_count=200000)
print(f"[1/3] is_stale(200000) with no metadata: {stale} ✅")
assert stale is True, "Should be stale when no metadata"

# Test staleness detection (fresh scenario)
bm25._metadata = {"chunk_count": 200000, "build_timestamp": "test"}
stale = bm25.is_stale(qdrant_point_count=200500)  # < 5% drift
print(f"[2/3] is_stale(200500) with 200000 in metadata: {stale} ✅")
assert stale is False, "Should NOT be stale with < 5% drift"

# Test staleness detection (stale scenario)
stale = bm25.is_stale(qdrant_point_count=250000)  # > 5% drift
print(f"[3/3] is_stale(250000) with 200000 in metadata: {stale} ✅")
assert stale is True, "Should be stale with > 5% drift"

print()
print("=" * 60)
print("  ALL BM25 LIFECYCLE TESTS PASSED ✅")
print("=" * 60)
