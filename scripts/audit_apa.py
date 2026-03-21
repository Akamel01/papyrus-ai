"""Fast sampled audit of APA reference coverage in Qdrant."""
import random
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

client = QdrantClient(host="localhost", port=6334, timeout=60)
collection = "sme_papers_v2"

info = client.get_collection(collection)
total = info.points_count
print(f"Total points: {total}")

# Use scroll with a limit to get a representative sample
# Qdrant scroll returns points in order, so we get multiple pages
# to sample from different parts of the collection

has_apa = 0
missing_apa = 0
has_doi = 0
missing_doi = 0
unique_dois_with = set()
unique_dois_without = set()
sample_missing = []
sample_has = []

# Sample 5 batches of 200 from different offsets
checked = 0
offsets = [None]  # Start from beginning

for batch_num in range(20):  # 20 batches x 100 = 2000 samples
    results, next_offset = client.scroll(
        collection_name=collection,
        limit=100,
        offset=offsets[-1],
        with_payload=True,
        with_vectors=False,
    )
    if not results:
        break
    
    for point in results:
        payload = point.payload or {}
        doi = payload.get("doi", "")
        apa = payload.get("apa_reference", "")
        
        if doi:
            has_doi += 1
        else:
            missing_doi += 1
        
        if apa and apa.strip():
            has_apa += 1
            if doi:
                unique_dois_with.add(doi)
            if len(sample_has) < 3:
                sample_has.append(f"DOI={doi[:60]} | APA={apa[:130]}")
        else:
            missing_apa += 1
            if doi:
                unique_dois_without.add(doi)
            if len(sample_missing) < 5:
                keys = list(payload.keys())
                sample_missing.append(f"DOI={doi[:60]} | keys={keys}")
        checked += 1
    
    if next_offset is None:
        break
    offsets.append(next_offset)

pct_has = (has_apa / checked * 100) if checked else 0
pct_miss = (missing_apa / checked * 100) if checked else 0

print(f"\n=== APA REFERENCE AUDIT (sampled {checked} chunks) ===")
print(f"Has apa_reference:     {has_apa:>5} ({pct_has:.1f}%)")
print(f"Missing apa_reference: {missing_apa:>5} ({pct_miss:.1f}%)")
print(f"Has DOI:               {has_doi:>5} ({has_doi/checked*100:.1f}%)")
print(f"Missing DOI:           {missing_doi:>5}")
print(f"\nUnique DOIs with APA:    {len(unique_dois_with)}")
print(f"Unique DOIs without APA: {len(unique_dois_without)}")
overlap = unique_dois_with & unique_dois_without
print(f"Mixed coverage DOIs:     {len(overlap)}")

print(f"\n--- SAMPLE: WITH apa_reference ---")
for s in sample_has:
    print(f"  {s}")

print(f"\n--- SAMPLE: MISSING apa_reference ---")
for s in sample_missing:
    print(f"  {s}")
