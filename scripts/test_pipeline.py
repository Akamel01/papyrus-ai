#!/usr/bin/env python
"""Quick test of embedding and storage pipeline."""

import sys
sys.path.insert(0, '.')

from src.utils.helpers import load_config
from src.indexing import create_embedder, create_vector_store
from src.ingestion import create_parser, create_chunker
from pathlib import Path

# Load config
config = load_config('config/config.yaml')
embed_device = config.get('embedding', {}).get('device', 'cpu')
print(f'Embedding device from config: {embed_device}')

# Test parsing first PDF
papers = list(Path('DataBase/Papers').glob('*.pdf'))[:1]
parser = create_parser(quality_threshold=0.5)
chunker = create_chunker()
doc = parser.parse(papers[0])
chunks = chunker.chunk(doc)
print(f'Parsed: {doc.doi}, {len(chunks)} chunks')

# Test embedding on configured device
try:
    embedder = create_embedder(
        device=embed_device,
        batch_size=32
    )
    print(f'Embedding {len(chunks)} chunks on {embed_device}...')
    texts = [c.text for c in chunks]
    embeddings = embedder.embed(texts)
    print(f'Got {len(embeddings)} embeddings, dim={len(embeddings[0])}')
except Exception as e:
    print(f'CUDA embedding failed: {e}')
    print('Falling back to CPU...')
    embedder = create_embedder(device='cpu', batch_size=32)
    texts = [c.text for c in chunks]
    embeddings = embedder.embed(texts)
    print(f'Got {len(embeddings)} embeddings on CPU, dim={len(embeddings[0])}')

# Attach and upsert
for chunk, emb in zip(chunks, embeddings):
    chunk.embedding = emb

vs = create_vector_store()
vs.create_collection()
vs.upsert(chunks)
count = vs.count()
print(f'Upserted to Qdrant. Count: {count}')
print('SUCCESS!' if count > 0 else 'FAILED - no data stored')
