import sys
import json
from qdrant_client import QdrantClient
from qdrant_client.http import models

def check_qdrant_stream():
    client = QdrantClient(host="localhost", port=6334)
    collection_name = "sme_papers_v2"
    
    recent_dois = [
        "10.48550/arxiv.2408.15136",
        "10.1201/9781003323020-233",
        "10.24963/ijcai.2020/659",
        "10.1186/s12909-022-03141-z",
        "10.61173/86rnrr18"
    ]
    
    results = {}
    
    for doi in recent_dois:
        # Search for chunks associated with this DOI
        scroll_res, _ = client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doi",
                        match=models.MatchValue(value=doi)
                    )
                ]
            ),
            limit=5, # Get just a few chunks to check schema
            with_payload=True,
            with_vectors=True
        )
        
        # also get total count for this DOI
        count_res = client.count(
            collection_name=collection_name,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doi",
                        match=models.MatchValue(value=doi)
                    )
                ]
            )
        )
        
        chunks_info = []
        for point in scroll_res:
            dim = len(point.vector) if point.vector else 0
            
            # extract payload schema footprint
            payload_keys = list(point.payload.keys())
            metadata_keys = list(point.payload.get("metadata", {}).keys())
            
            chunks_info.append({
                "id": str(point.id),
                "dimension": dim,
                "payload_schema": payload_keys,
                "metadata_schema": metadata_keys
            })
            
        results[doi] = {
            "total_chunks_in_v2": count_res.count,
            "sample_chunks": chunks_info
        }
        
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    check_qdrant_stream()
