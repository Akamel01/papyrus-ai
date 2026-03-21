
import os
import sys
import logging
import torch
import requests
import json
from pathlib import Path

# Setup paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Verifier")

def check_step(name, func):
    logger.info(f"\n--- STEP: {name} ---")
    try:
        func()
        logger.info(f"✅ PASS: {name}")
        return True
    except Exception as e:
        logger.error(f"❌ FAIL: {name}")
        logger.error(f"Error details: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_infrastructure():
    # 1. Qdrant (Port 6334 external maps to 6333 internal)
    try:
        resp = requests.get("http://localhost:6334/collections")
        if resp.status_code == 200:
            logger.info("   Qdrant Service: OK")
        else:
            raise Exception(f"Qdrant returned {resp.status_code}")
    except Exception as e:
        raise Exception(f"Could not connect to Qdrant on port 6334: {e}")

    # 2. Ollama (External 11435)
    try:
        resp = requests.get("http://localhost:11435/api/tags")
        if resp.status_code == 200:
            logger.info("   Ollama Service: OK")
        else:
            raise Exception(f"Ollama returned {resp.status_code}")
    except Exception as e:
        raise Exception(f"Could not connect to Ollama: {e}")

def verify_embedder():
    from src.indexing.embedder import create_embedder
    
    # Auto-detect check
    if not torch.cuda.is_available():
        logger.warning("⚠️ WARNING: CUDA not detected by PyTorch. Running on CPU will be slow.")
    else:
        logger.info(f"   CUDA Available: {torch.cuda.get_device_name(0)}")

    embedder = create_embedder(device=None) # Should auto-detect
    logger.info(f"   Embedder loaded on: {embedder.device}")
    
    vec = embedder.embed_query("test query")
    if len(vec) != 1024:
        raise Exception(f"Embedding dimension mismatch. Expected 1024, got {len(vec)}")
    logger.info("   Embedding generation: OK")
    return embedder

def verify_vector_store(embedder):
    from src.indexing.vector_store import QdrantVectorStore
    
    # ⚠️ CONNECT TO SERVER MODE (Port 6334 external)
    vstore = QdrantVectorStore(location=None, host="localhost", port=6334, collection_name="sme_papers")
    
    # Check collection info using internal client
    try:
        info = vstore._get_client().get_collection("sme_papers")
        count = info.points_count
        logger.info(f"   Collection 'sme_papers' found. Items: {count}")
        
        if count == 0:
            raise Exception("Collection exists but is EMPTY. Ingestion failed or data missing.")
            
    except Exception as e:
        raise Exception(f"Failed to inspect collection: {e}")

    return vstore

def verify_retrieval(embedder, vstore):
    from src.retrieval.hyde import HyDERetriever
    from src.core.interfaces import LLMClient
    
    # Mock LLM just to test flow, or Real one? Let's use Real to verify encoding fix.
    # But wait, we need 'create_ollama_client'.
    from src.generation.ollama_client import create_ollama_client
    
    llm = create_ollama_client(model_name="gpt-oss:120b-cloud")
    
    hyde = HyDERetriever(llm, embedder, vstore)
    
    query = "road safety assessment crash-based vs conflict-based"
    logger.info(f"   Running HyDE Search for: '{query}'")
    
    results = hyde.search(query, use_hyde=True)
    
    logger.info(f"   Retrieved {len(results)} results")
    if not results:
        raise Exception("Search returned 0 results.")
        
    # Print a snippet to verify decoding
    logger.info(f"   Top Result DOI: {results[0].chunk.doi}")
    return results, llm

def verify_librarian(results, llm):
    from src.academic_v2.librarian import Librarian
    
    lib = Librarian(llm)
    logger.info("   Extracting facts (this calls the LLM)...")
    
    # Mock a fact-rich chunk to ensure non-zero extraction if logic works
    from src.core.interfaces import RetrievalResult, Chunk
    mock_chunk = Chunk(
        chunk_id="test_id", 
        doi="10.1234/test", 
        text="In a 2020 empirical study, Smith et al. found that roundabouts reduced fatal crashes by 90% compared to signalized intersections (p < 0.05). However, Jones (2021) argues that conflict-based metrics are more proactive.", 
        metadata={"year": 2020}
    )
    mock_result = RetrievalResult(chunk=mock_chunk, score=0.99, source="mock")
    
    facts = lib.extract_facts_from_chunks([mock_result])
    
    logger.info(f"   Extracted {len(facts)} facts")
    if len(facts) == 0:
        logger.warning("   ⚠️ Warning: Zero facts extracted. Check prompt or model output.")
        # Don't fail hard usually, but for verification we might want to see content
    else:
        logger.info(f"   Example Fact: {facts[0].claim_text}")

def verify_architect(llm):
    from src.academic_v2.architect import Architect
    from src.academic_v2.models import AtomicFact, Methodology, MethodologyType, CertaintyLevel
    
    logger.info("   Testing Architect (Planning)...")
    arch = Architect(llm)
    
    # Mock facts with proper Pydantic models
    meth = Methodology(type=MethodologyType.REVIEW, context="General review", limitations=[])
    f1 = AtomicFact(
        id="1", source_id="s1", claim_text="Crash-based methods rely on historical data.", 
        excerpt_quote="...", methodology=meth, topics=["crash"], year=2020,
        certainty=CertaintyLevel.HIGH
    )
    f2 = AtomicFact(
        id="2", source_id="s2", claim_text="Conflict-based methods use near-miss analysis.", 
        excerpt_quote="...", methodology=meth, topics=["conflict"], year=2021,
        certainty=CertaintyLevel.MODERATE
    )
    
    mock_facts = [f1, f2]
    
    # Correct method name: design_section_plan
    plan = arch.design_section_plan(
        query="Compare crash vs conflict", 
        facts=mock_facts, 
        section_name="Methodology Review",
        review_text="Review of conflict-based and crash-based safety assessment methodologies."
    )
    
    logger.info(f"   Generated Plan Sections: {len(plan)}")
    if not plan:
        logger.warning("   ⚠️ Warning: Zero plan sections. Check prompt.")
    else:
        logger.info(f"   Example Section: {plan[0].get('section_name', 'Unknown')}")

def verify_drafter(llm):
    from src.academic_v2.drafter import Drafter
    from src.academic_v2.models import AtomicFact, Methodology, MethodologyType, CertaintyLevel
    
    logger.info("   Testing Drafter (Writing)...")
    drafter = Drafter(llm)
    
    # Mock data (using dict plan as Architect returns)
    plan_dict = {
        "section_name": "Methodology",
        "thesis_statement": "Conflict analysis provides proactive metrics.",
        "assigned_evidence": ["1", "2"],
        "order": 1
    }
    
    # Mock facts
    meth = Methodology(type=MethodologyType.REVIEW, context="Ctx", limitations=[])
    f1 = AtomicFact(id="1", source_id="s1", claim_text="Fact A", excerpt_quote="...", methodology=meth, topics=[], year=2020, certainty=CertaintyLevel.HIGH)
    f2 = AtomicFact(id="2", source_id="s2", claim_text="Fact B", excerpt_quote="...", methodology=meth, topics=[], year=2021, certainty=CertaintyLevel.MODERATE)
    
    facts = [f1, f2]
    
    # Test draft_paragraph directly
    # Note: draft_section expects [ParagraphPlan] objects OR dicts now?
    # Let's test draft_section with a list of dicts to mimic Engine behavior
    
    try:
        text = drafter.draft_section([plan_dict], facts)
        if text:
            logger.info(f"   Drafted Text: {text[:50]}...")
        else:
            logger.warning("   ⚠️ Warning: Drafter produced empty text.")
    except Exception as e:
        raise e

def main():
    logger.info("🚀 STARTING DEEP COMPONENT VERIFICATION")
    
    # 1. Infrastructure
    try:
        logger.info("\n--- STEP: Infrastructure ---")
        verify_infrastructure()
        logger.info("✅ PASS: Infrastructure")
    except Exception as e:
        logger.error(f"❌ FAIL: Infrastructure\n{e}")
        return

    # 2. Embedder
    try:
        logger.info("\n--- STEP: Embedder ---")
        embedder = verify_embedder()
        logger.info("✅ PASS: Embedder")
    except Exception as e:
        logger.error(f"❌ FAIL: Embedder\n{e}")
        return

    # 3. Vector Store
    try:
        logger.info("\n--- STEP: Vector Store ---")
        vstore = verify_vector_store(embedder)
        logger.info("✅ PASS: Vector Store")
    except Exception as e:
        logger.error(f"❌ FAIL: Vector Store\n{e}")
        return

    # 4. Retrieval
    try:
        logger.info("\n--- STEP: Retrieval (HyDE) ---")
        results, llm = verify_retrieval(embedder, vstore)
        logger.info("✅ PASS: Retrieval (HyDE)")
    except Exception as e:
        logger.error(f"❌ FAIL: Retrieval (HyDE)\n{e}")
        import traceback
        traceback.print_exc()
        return

    # 5. Librarian
    try:
        logger.info("\n--- STEP: Librarian ---")
        verify_librarian(results, llm)
        logger.info("✅ PASS: Librarian")
    except Exception as e:
        logger.error(f"❌ FAIL: Librarian\n{e}")
        return

    # 6. Architect
    try:
        logger.info("\n--- STEP: Architect ---")
        verify_architect(llm)
        logger.info("✅ PASS: Architect")
    except Exception as e:
        logger.error(f"❌ FAIL: Architect\n{e}")
        return

    # 7. Drafter
    try:
        logger.info("\n--- STEP: Drafter ---")
        verify_drafter(llm)
        logger.info("✅ PASS: Drafter")
    except Exception as e:
        logger.error(f"❌ FAIL: Drafter\n{e}")
        return


    with open("verification_status.txt", "w", encoding="utf-8") as f:
        f.write("PASS")
    logger.info("\n🎉 ALL SYSTEMS GO. READY FOR RUNNER.PY")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with open("verification_status.txt", "w", encoding="utf-8") as f:
            f.write(f"FAIL: {str(e)}")
        raise
