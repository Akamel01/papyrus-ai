#!/usr/bin/env python3
"""
SME Collection Migration Script (v2 — streaming)

Uses a TWO-COLLECTION streaming approach to avoid OOM:
  1. Create a NEW collection with optimized config
  2. Stream vectors from OLD → NEW in small batches (scroll → upsert)
  3. Delete OLD collection once migration verified
  4. Rename NEW → OLD (by creating alias or just updating config)
  5. Wait for HNSW index readiness
  6. Rebuild BM25 index

This approach never holds more than one batch (~1000 vectors) in memory.

Usage (inside Docker):
    python scripts/migrate_collection.py

Usage (outside Docker):
    python scripts/migrate_collection.py --host localhost --port 6334
"""

import sys
import time
import logging
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress verbose httpx logging
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("migration")


def stream_migrate(
    client,
    src_collection: str,
    dst_collection: str,
    scroll_batch: int = 500,
    upsert_batch: int = 100,
):
    """
    Stream points from src → dst in batches.
    Never holds more than scroll_batch points in memory.
    """
    from qdrant_client.http import models

    offset = None
    total_migrated = 0
    start = time.time()

    while True:
        # Scroll a batch from source
        results, next_offset = client.scroll(
            collection_name=src_collection,
            limit=scroll_batch,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        if not results:
            break

        # Convert to PointStruct and upsert to destination
        point_structs = [
            models.PointStruct(
                id=p.id,
                vector=p.vector,
                payload=p.payload,
            )
            for p in results
        ]

        # Upsert in sub-batches
        for i in range(0, len(point_structs), upsert_batch):
            batch = point_structs[i:i + upsert_batch]
            client.upsert(
                collection_name=dst_collection,
                points=batch,
                wait=True,
            )

        total_migrated += len(results)
        elapsed = time.time() - start
        rate = total_migrated / elapsed if elapsed > 0 else 0

        if total_migrated % 50000 == 0 or next_offset is None:
            logger.info(
                f"[STREAM] {total_migrated:,} points migrated "
                f"| {rate:.0f} pts/s | elapsed={elapsed/60:.1f} min"
            )

        # Free memory
        del results, point_structs

        if next_offset is None:
            break
        offset = next_offset

    elapsed = time.time() - start
    logger.info(
        f"[STREAM] ✅ Complete: {total_migrated:,} points in {elapsed/60:.1f} min "
        f"({total_migrated/elapsed:.0f} pts/s)"
    )
    return total_migrated


def wait_for_index(client, collection_name: str, threshold: float = 0.95, timeout: int = 3600, poll_sec: int = 10):
    """Wait for HNSW index to reach threshold completeness."""
    logger.info(f"[INDEX-GATE] Waiting for index ≥{threshold*100:.0f}% (timeout={timeout}s)...")

    start = time.time()

    while True:
        info = client.get_collection(collection_name)
        total = info.points_count or 0
        indexed = info.indexed_vectors_count or 0
        completeness = (indexed / total) if total > 0 else 1.0

        elapsed = time.time() - start

        opt_status = "unknown"
        if hasattr(info, "optimizer_status") and info.optimizer_status:
            opt_status = str(getattr(info.optimizer_status, "status", info.optimizer_status))

        logger.info(
            f"[INDEX-GATE] {completeness*100:.2f}% "
            f"({indexed:,}/{total:,}) | optimizer={opt_status} | "
            f"elapsed={elapsed/60:.1f} min"
        )

        if completeness >= threshold:
            logger.info(f"[INDEX-GATE] ✅ Index ready in {elapsed/60:.1f} min")
            return True

        if elapsed >= timeout:
            logger.error(f"[INDEX-GATE] ❌ TIMEOUT after {elapsed/60:.1f} min")
            return False

        time.sleep(poll_sec)


def main():
    parser = argparse.ArgumentParser(description="Migrate sme_papers to optimized config (streaming)")
    parser.add_argument("--host", default="qdrant", help="Qdrant host")
    parser.add_argument("--port", type=int, default=6333, help="Qdrant port")
    parser.add_argument("--collection", default="sme_papers", help="Source collection name")
    parser.add_argument("--scroll-batch", type=int, default=500, help="Scroll batch size (smaller = less memory)")
    parser.add_argument("--upsert-batch", type=int, default=100, help="Upsert batch size")
    parser.add_argument("--bm25-path", default="data/bm25_index.pkl", help="BM25 index path")
    parser.add_argument("--skip-bm25", action="store_true", help="Skip BM25 rebuild")
    parser.add_argument("--dry-run", action="store_true", help="Pre-flight only, don't migrate")
    args = parser.parse_args()

    from qdrant_client import QdrantClient
    from qdrant_client.http import models

    client = QdrantClient(host=args.host, port=args.port, timeout=300)
    logger.info(f"[CONNECT] Connected to Qdrant at {args.host}:{args.port}")

    src = args.collection
    dst = f"{args.collection}_v2"

    # ── Pre-flight checks ──
    try:
        info = client.get_collection(src)
        total = info.points_count or 0
        logger.info(f"[PRE-FLIGHT] Source '{src}': {total:,} points")

        if total == 0:
            logger.error("[PRE-FLIGHT] ❌ Collection is empty!")
            sys.exit(1)

        hnsw_cfg = info.config.hnsw_config
        logger.info(f"[PRE-FLIGHT] Current: m={hnsw_cfg.m}, ef_construct={hnsw_cfg.ef_construct}")
        logger.info(f"[PRE-FLIGHT] Quantization: {info.config.quantization_config or 'NONE'}")
    except Exception as e:
        logger.error(f"[PRE-FLIGHT] ❌ Cannot access collection: {e}")
        sys.exit(1)

    # Detect dimension
    sample, _ = client.scroll(src, limit=1, with_vectors=True)
    if not sample:
        logger.error("[PRE-FLIGHT] ❌ No points found")
        sys.exit(1)
    dimension = len(sample[0].vector)
    logger.info(f"[PRE-FLIGHT] Dimension: {dimension}")
    logger.info(f"[PRE-FLIGHT] Target: m=32, ef_construct=128, SQ-int8, on_disk=True")

    if args.dry_run:
        logger.info(f"[DRY-RUN] Would migrate {total:,} points. Exiting.")
        sys.exit(0)

    migration_start = time.time()

    # ━━━━ STEP 1: Create destination collection with optimized config ━━━━
    logger.info("=" * 60)
    logger.info("  STEP 1/5: Creating destination collection with optimized config")
    logger.info("=" * 60)

    # Delete destination if it already exists (from a previous failed run)
    try:
        client.get_collection(dst)
        logger.warning(f"[CREATE] Destination '{dst}' already exists — deleting it first")
        client.delete_collection(dst)
    except Exception:
        pass  # Doesn't exist, good

    m = 32
    ef_construct = 128

    client.create_collection(
        collection_name=dst,
        vectors_config=models.VectorParams(
            size=dimension,
            distance=models.Distance.COSINE,
            on_disk=True,
        ),
        hnsw_config=models.HnswConfigDiff(
            m=m,
            ef_construct=ef_construct,
            full_scan_threshold=20000,
            max_indexing_threads=0,
            on_disk=False,
        ),
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8,
                quantile=0.99,
                always_ram=True,
            )
        ),
        optimizers_config=models.OptimizersConfigDiff(
            default_segment_number=4,
            max_segment_size=200000,
            indexing_threshold=20000,
            flush_interval_sec=5,
        ),
        on_disk_payload=True,
    )

    # Payload indexes
    client.create_payload_index(dst, "doi", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(dst, "section", models.PayloadSchemaType.KEYWORD)

    logger.info(
        f"[CREATE] ✅ Created '{dst}': dim={dimension}, m={m}, "
        f"ef_construct={ef_construct}, SQ-int8, on_disk=True"
    )

    # ━━━━ STEP 2: Stream vectors from old → new ━━━━
    logger.info("=" * 60)
    logger.info(f"  STEP 2/5: Streaming {total:,} vectors from '{src}' → '{dst}'")
    logger.info("=" * 60)

    migrated = stream_migrate(
        client, src, dst,
        scroll_batch=args.scroll_batch,
        upsert_batch=args.upsert_batch,
    )

    # Verify counts match
    dst_info = client.get_collection(dst)
    dst_count = dst_info.points_count or 0
    logger.info(f"[VERIFY] Source: {total:,} → Destination: {dst_count:,}")

    if dst_count < total * 0.99:
        logger.error(
            f"[VERIFY] ❌ Count mismatch! Expected ~{total:,}, got {dst_count:,}. "
            f"Keeping source collection for safety."
        )
        sys.exit(1)

    # ━━━━ STEP 3: Delete old, rename new ━━━━
    logger.info("=" * 60)
    logger.info("  STEP 3/5: Swapping collections")
    logger.info("=" * 60)

    client.delete_collection(src)
    logger.info(f"[SWAP] Deleted old '{src}'")

    # Qdrant doesn't have rename — create an alias or just use the new name
    # We'll recreate with the original name and migrate again from v2
    # Actually, simpler: update the collection name in our config
    # BUT the simplest approach: recreate src from dst, then delete dst
    # ... actually let's just use collection aliases

    # Try using update_collection_aliases if available, otherwise we'll do a final
    # stream from dst → src (both have optimized config, so this is fast)
    try:
        client.update_collection_aliases(
            change_aliases_operations=[
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=dst,
                        alias_name=src,
                    )
                )
            ]
        )
        logger.info(f"[SWAP] ✅ Created alias '{src}' → '{dst}'")
    except Exception as e:
        logger.warning(f"[SWAP] Alias not supported ({e}), using direct rename approach")
        # Create new collection with the original name, same config
        client.create_collection(
            collection_name=src,
            vectors_config=models.VectorParams(
                size=dimension,
                distance=models.Distance.COSINE,
                on_disk=True,
            ),
            hnsw_config=models.HnswConfigDiff(
                m=m, ef_construct=ef_construct,
                full_scan_threshold=20000, max_indexing_threads=0, on_disk=False,
            ),
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8, quantile=0.99, always_ram=True,
                )
            ),
            optimizers_config=models.OptimizersConfigDiff(
                default_segment_number=4, max_segment_size=200000,
                indexing_threshold=20000, flush_interval_sec=5,
            ),
            on_disk_payload=True,
        )
        client.create_payload_index(src, "doi", models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(src, "section", models.PayloadSchemaType.KEYWORD)

        logger.info(f"[SWAP] Streaming from '{dst}' → '{src}'...")
        stream_migrate(client, dst, src, scroll_batch=args.scroll_batch, upsert_batch=args.upsert_batch)

        # Verify
        src_info = client.get_collection(src)
        src_count = src_info.points_count or 0
        if src_count >= dst_count * 0.99:
            client.delete_collection(dst)
            logger.info(f"[SWAP] ✅ Deleted temp '{dst}'. Final collection: '{src}' with {src_count:,} points")
        else:
            logger.error(f"[SWAP] ❌ Count mismatch after rename stream! Keeping both collections.")
            sys.exit(1)

    # ━━━━ STEP 4: Wait for HNSW index readiness ━━━━
    logger.info("=" * 60)
    logger.info("  STEP 4/5: Waiting for HNSW index ≥95%")
    logger.info("=" * 60)

    # Check which collection to gate on (alias or direct)
    try:
        target_info = client.get_collection(src)
        gate_collection = src
    except Exception:
        gate_collection = dst

    index_ready = wait_for_index(client, gate_collection, threshold=0.95, timeout=3600)

    if not index_ready:
        logger.error("[INDEX] ❌ Index did not reach 95%. Continuing anyway...")

    # ━━━━ STEP 5: Rebuild BM25 index ━━━━
    if not args.skip_bm25:
        logger.info("=" * 60)
        logger.info("  STEP 5/5: Rebuilding BM25 index")
        logger.info("=" * 60)

        from src.indexing.bm25_index import BM25Index
        bm25 = BM25Index(index_path=args.bm25_path)
        chunk_count = bm25.rebuild_from_qdrant(
            qdrant_client=client,
            collection_name=gate_collection,
            scroll_batch_size=args.scroll_batch,
        )
        logger.info(f"[BM25] ✅ BM25 index rebuilt with {chunk_count:,} chunks")
    else:
        logger.info("[BM25] Skipped (--skip-bm25)")

    # ━━━━ DONE ━━━━
    total_elapsed = time.time() - migration_start
    logger.info("=" * 60)
    logger.info("  MIGRATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Vectors migrated:  {migrated:,}")
    logger.info(f"  Config:            m={m}, ef_construct={ef_construct}, SQ-int8, on_disk=True")
    logger.info(f"  Index ready:       {'✅' if index_ready else '⚠️'}")
    logger.info(f"  Total time:        {total_elapsed/60:.1f} minutes")
    logger.info("=" * 60)

    final = client.get_collection(gate_collection)
    logger.info(
        f"[VERIFY] Final: {final.points_count:,} points, "
        f"{final.indexed_vectors_count:,} indexed, "
        f"status={final.status.value}"
    )


if __name__ == "__main__":
    main()
