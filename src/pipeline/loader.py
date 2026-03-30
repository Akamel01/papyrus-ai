
import logging
import sys
from pathlib import Path

# Add project root to path if needed (though usually handled by execution context)
# sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.helpers import load_config
from src.retrieval import create_hybrid_search, create_reranker, create_context_builder
from src.generation import create_ollama_client, create_prompt_builder
from src.indexing import create_bm25_index
from src.indexing.qdrant_optimizer import run_startup_optimization

logger = logging.getLogger(__name__)

def load_rag_pipeline_core(config_path="config/config.yaml", headless=False):
    """
    Core logic to load the RAG pipeline.
    This function is decoupled from Streamlit to allow headless testing.
    
    Args:
        config_path: Path to config.yaml
        headless: If True, skips Streamlit-specific checks if any (mostly for reference).
    
    Returns:
        dict: The initialized pipeline dictionary.
    """
    logger.info("Initializing RAG Pipeline Core...")

    config = load_config(config_path)

    import os
    skip_gate = os.environ.get("SKIP_INDEX_GATE", "false").lower() == "true"

    # 1. Run Auto-Tuner & Safety Gates
    # startup optimization logs internally
    opt_result = run_startup_optimization(
        config=config,
        skip_index_gate=skip_gate
    )
    
    if opt_result.get("status") == "FAILED":
        error_msg = f"Startup Optimization Failed: {opt_result.get('error')}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Inject optimized parameters
    if opt_result.get("status") != "FAILED":
        config["optimized_params"] = opt_result.get("optimal_params")
        
    # Load BM25 index (Only if enabled)
    bm25_conf = config.get("bm25", {})
    bm25_index = None

    if config.get("retrieval", {}).get("bm25_weight", 0.0) >= 0:
            bm25_index = create_bm25_index(
            index_path=bm25_conf.get("index_path", "data/bm25_index.pkl"),
            tokenizer_type=bm25_conf.get("tokenizer", "word"),
            remove_stopwords=bm25_conf.get("remove_stopwords", True),
            use_tantivy=True
        )
    else:
        logger.info("BM25 disabled in config.")

    # Create pipeline components
    logger.info("Creating pipeline components...")
    pipeline = {
        "config": config,
        "hybrid_search": create_hybrid_search(config),
        "reranker": create_reranker(
            model_name=config.get("retrieval", {}).get(
                "reranker_remote_model" if config.get("retrieval", {}).get("reranker_remote_url") else "reranker_model",
                "BAAI/bge-reranker-v2-m3"
            ),
            device=config.get("retrieval", {}).get("reranker_device", "cpu"),
            enabled=config.get("retrieval", {}).get("use_reranker", True),
            remote_url=config.get("retrieval", {}).get("reranker_remote_url"),
            max_parallel=config.get("retrieval", {}).get("reranker_max_parallel", 128),
            batch_size=config.get("retrieval", {}).get("reranker_batch_size", 128),
            max_length=config.get("retrieval", {}).get("reranker_max_length", 512),
            dtype=config.get("retrieval", {}).get("reranker_dtype", "fp16"),
        ),
        "context_builder": create_context_builder(
            max_context_tokens=config.get("generation", {}).get("max_context_length", 6000),
            deduplicate=config.get("generation", {}).get("context_deduplication", True)
        ),
        "llm": create_ollama_client(
            model_name=config.get("generation", {}).get("model_name", "gemma:7b"),
            base_url=config.get("generation", {}).get("base_url", "http://localhost:11434"),
            timeout=config.get("generation", {}).get("timeout", 120),
            num_ctx=config.get("generation", {}).get("num_ctx", 32768)
        ),
        "prompt_builder": create_prompt_builder("config/prompts.yaml"),
        "bm25_index": bm25_index
    }

    # Eagerly load models
    # This is the heavy part
    try:
        logger.info("Core: Calling embedder.load()...")
        pipeline["hybrid_search"].embedder.load()
        logger.info("Core: embedder.load() returned.")
        
        logger.info("Core: Calling reranker.load()...")
        pipeline["reranker"].load()
        logger.info("Core: reranker.load() returned.")
        
    except Exception as e:
        logger.warning(f"Core: Eager loading warning: {e}")
        # In strict headless mode, maybe we want to raise?
        # But for compatibility, we log.
        if headless:
            logger.error("Headless loading failed.")
            raise e

    logger.info("RAG Pipeline Core Loaded Successfully.")
    return pipeline
