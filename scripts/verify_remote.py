import sys
import os
import logging

# Add project root
sys.path.append(os.getcwd())

from src.indexing.embedder_remote import RemoteEmbedder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY_REMOTE")

def main():
    logger.info("Starting RemoteEmbedder Verification...")
    
    # URL pointing to the OTHER container
    url = "http://sme_ollama:11434"
    model = "qwen3-embedding:8b"
    
    logger.info(f"Connecting to {url} for model {model}...")
    
    try:
        embedder = RemoteEmbedder(model_name=model, base_url=url)
        embedder.load()
        logger.info(f"✅ Loaded. Dimension: {embedder.dimension}")
        
        texts = ["This is a test sentence for embedding generation.", "Another sentence."]
        logger.info(f"Embedding {len(texts)} texts...")
        
        embeddings = embedder.embed(texts)
        
        if not embeddings:
            logger.error("❌ No embeddings returned!")
            sys.exit(1)
            
        logger.info(f"✅ Generated {len(embeddings)} embeddings.")
        logger.info(f"Vector 0 sample: {embeddings[0][:5]}... (Len: {len(embeddings[0])})")
        
        if len(embeddings[0]) != 4096 and len(embeddings[0]) != 1024:
             logger.warning(f"⚠️ Unexpected dimension: {len(embeddings[0])}. Expected 4096 or 1024.")
        
        logger.info("VERIFICATION SUCCESSFUL: Remote Embedding Works!")
        
    except Exception as e:
        logger.error(f"❌ Verification Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
