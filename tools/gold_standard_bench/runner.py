
"""
Recursive Optimization Loop (The Runner).

This script orchestrates the optimization process.
It:
1. Runs the RAG pipeline.
2. Grades the output.
3. If < 100% compliant, patches the code.
4. Repeats.
"""

import sys
import os
import json
import yaml # Added for config loading
import torch # Added for CUDA check
import warnings
import logging


# Force CUDA for main process if available
# Force CUDA for main process if available
try:
    print(f"DEBUG: Python Executable: {sys.executable}")
    print(f"DEBUG: Python Prefix: {sys.prefix}")
    print(f"DEBUG: Torch File: {torch.__file__}")
    print(f"DEBUG: Torch Version: {torch.__version__}")
    print(f"DEBUG: CUDA Available: {torch.cuda.is_available()}")
    print(f"DEBUG: CUDA Version: {torch.version.cuda}")
    print(f"DEBUG: Device Count: {torch.cuda.device_count()}")
    
    if torch.cuda.is_available():
        os.environ['CUDA_VISIBLE_DEVICES'] = '0'
        print(f"DEBUG: Force-enabled CUDA_VISIBLE_DEVICES=0")
    else:
        print("DEBUG: CUDA NOT DETECTED! Reranker will likely fail.")
except Exception as e:
    print(f"DEBUG: CUDA check failed: {e}")

# DB Path - User specified existing DB
DB_PATH = os.path.abspath("data/qdrant") 

# Configure Ollama with verified port 11435 globally
os.environ['OLLAMA_HOST'] = "http://ollama:11434" 

import logging
import time
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parents[2]))

from src.generation.ollama_client import create_ollama_client
from src.retrieval.sequential_rag import SequentialRAG
from src.academic_v2.engine import AcademicEngine
from tests.gold_standard.evaluator import CriteriaComplianceMatrix
from tools.gold_standard_bench.refiner import CodeRefiner

# Config
LOG_DIR = Path("tools/gold_standard_bench/runs")
if not LOG_DIR.exists():
    LOG_DIR.mkdir(parents=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "runner.log")
    ]
)


# Suppress Streamlit "missing ScriptRunContext" warnings aggressivley
# 1. Filter warnings module
warnings.filterwarnings("ignore", message=".*missing ScriptRunContext.*")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit")

# 2. Custom Filter
class NoContextWarningsFilter(logging.Filter):
    def filter(self, record):
        return "missing ScriptRunContext" not in record.getMessage()

# Apply to Streamlit specific loggers
logging.getLogger("streamlit").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner.script_run_context").setLevel(logging.ERROR)

# Apply filter to root and known streamlit loggers
logging.getLogger().addFilter(NoContextWarningsFilter())
logging.getLogger("streamlit").addFilter(NoContextWarningsFilter())
for name in logging.root.manager.loggerDict:
    if "streamlit" in name:
        logging.getLogger(name).addFilter(NoContextWarningsFilter())

logger = logging.getLogger("Optimizer")

class OptimizationLoop:
    def __init__(self, model_name: str = "gpt-oss:120b-cloud"):
        self.model_name = model_name
        self.llm = create_ollama_client(
            base_url=os.environ.get('OLLAMA_HOST', "http://localhost:11434"),
            model_name=model_name, 
            timeout=300
        )
        self.evaluator = CriteriaComplianceMatrix(self.llm, model_name)
        
        # Pass log file to refiner for context-aware patching
        self.refiner = CodeRefiner(self.llm, os.getcwd(), model_name, log_file=LOG_DIR / "runner.log")
        
        # Mocks/Stubs for pipeline initialization
        # In a real run, we need the full pipeline. 
        # For this script to run standalone, we need to construct the pipeline dictionary.
        from src.indexing.embedder import create_embedder
        from src.indexing.vector_store import create_vector_store
        from src.indexing.bm25_index import create_bm25_index
        from src.retrieval.hybrid_search import create_hybrid_search
        from src.retrieval.context_builder import create_context_builder
        from src.generation.prompts import PromptBuilder
        
        self.pipeline = {
            "llm": self.llm,
            "embedder": None, # Mocks if possible, or real if env set
            "vector_store": None,
            "bm25": None,
            "retriever": None, # We need a real retriever or a mock
            "prompt_builder": PromptBuilder()
        }
        
    def _init_real_pipeline(self):
        """Initialize the real expensive components."""
        # Load Config
        try:
             with open("/app/config/config.yaml", "r") as f: # Docker
                 config = yaml.safe_load(f)
                 logger.info("Loaded config from /app/config/config.yaml")
        except FileNotFoundError:
             try:
                 with open("config/docker_config.yaml", "r") as f: # Local fallback
                     config = yaml.safe_load(f)
                     logger.info("Loaded config from config/docker_config.yaml")
             except FileNotFoundError:
                 logger.warning("Config file not found. Using hardcoded defaults.")
                 config = {}

        from src.indexing.embedder import create_embedder
        from src.indexing.vector_store import create_vector_store
        from src.indexing.bm25_index import create_bm25_index
        from src.retrieval.hybrid_search import HybridSearch
        from src.retrieval.reranker import create_reranker
        from src.retrieval.context_builder import ContextBuilder

        if torch.cuda.is_available():
            logger.info("Initializing Real Pipeline with CUDA Support")
            device = "cuda"
        else:
            logger.info("Initializing Real Pipeline on CPU")
            device = "cpu"
            
        embedder = create_embedder(device=device) 
        
        # Connect to Qdrant Server using Config
        v_conf = config.get("vector_store", {})
        vstore = create_vector_store(
            location=None, 
            host=v_conf.get("host", "qdrant"), 
            port=v_conf.get("port", 6333), 
            collection_name=v_conf.get("collection_name", "sme_papers")
        )
        
        # Configure Ollama Config
        gen_conf = config.get("generation", {})
        ollama_url = gen_conf.get("base_url", "http://ollama:11434")
        os.environ['OLLAMA_HOST'] = ollama_url
        logger.info(f"Configured Ollama Host: {ollama_url}")

        bm25 = create_bm25_index()
        reranker = create_reranker()
        context_builder = ContextBuilder()
        
        hybrid = HybridSearch(embedder, vstore, bm25)
        self.pipeline["hybrid_search"] = hybrid
        self.pipeline["reranker"] = reranker
        self.pipeline["embedder"] = embedder
        self.pipeline["vector_store"] = vstore
        self.pipeline["context_builder"] = context_builder

    def run_cycle(self, query: str, max_iterations: int = 50):
        """Run the optimization loop."""
        
        history = []
        
        # Try to init real pipeline, if fails, we can't run real queries
        try:
            self._init_real_pipeline()
        except Exception as e:
            logger.error(f"Failed to init pipeline: {e}. Aborting optimization.")
            return

        rag = SequentialRAG(self.pipeline, max_rounds=2)
        
        for i in range(max_iterations):
            logger.info(f"\nSTARTING ITERATION {i+1}/{max_iterations}")
            
            # 1. Generate
            logger.info("Generating content...")
            start_t = time.time()
            # We bypass the complex 'process_with_reflection' UI wrapper and call generation directly if possible
            # But process_with_reflection is the entry point.
            # We need a dummy status callback.
            # We use the generator for Section Mode (V2 Engine)
            # This handles "Let AI Decide" (adaptive planning) and "Sequential Thinking" (multi-step)
            # We consume the generator to completion to get the final result dictionary.
            # [TEST MODE] Interactive Callback for Phase Pausing
            def interactive_callback(msg):
                clean_msg = msg.encode('ascii', 'ignore').decode('ascii')
                logger.info(f"Status: {clean_msg}")
                
                # Phase 3 Checkpoint
                if "Initial research scan" in clean_msg:
                    print(f"\n[PHASE 3] Search Logic Starting: {clean_msg}")
                    input(">> Verify 'High Depth' logs above. Press Enter to proceed to Search...")

                # Phase 4 Checkpoint
                if "Generating Knowledge Map" in clean_msg:
                    print(f"\n[PHASE 4] Sequential Thinking Starting: {clean_msg}")
                    input(">> Verify Knowledge Map generation. Press Enter to proceed to Planning...")

                # Phase 5 Checkpoint
                if "Writing section 1/" in clean_msg:
                    print(f"\n[PHASE 5] Writing Loop Starting: {clean_msg}")
                    input(">> Verify Section Planning. Press Enter to proceed to Writing...")

            # Phase 2 Checkpoint (Launch)
            print("\n[PHASE 2] Launch & Initialization Complete.")
            input(">> Verify Init logs. Press Enter to Begin Phase 3 (Search)...")

            gen = rag.process_with_sections(
                query=query,
                depth="High",
                model=self.model_name,
                paper_range=(40, 60),
                auto_citation_density=True, 
                status_callback=interactive_callback
            )
            
            # Consume generator
            final_result = None
            try:
                for progress in gen:
                    pass # We just let it run
                
                # [TEST MODE] Manual Pause
                print(f"\n[TEST MODE] Step 1 (Generation) Complete.")
                input("Press Enter to continue to Step 2 (Assessment)...")

            except StopIteration as e:
                final_result = e.value
                
            # If generator returns via yield or return match
            if isinstance(final_result, dict):
                response = final_result.get("response", "")
            else:
                # Fallback if return value capture fails, though process_with_sections returns Dict
                # We might need to handle the StopIteration return properly if it wasn't caught above
                response = ""
                logger.error("Failed to capture final response from generator.")
            elapsed = time.time() - start_t
            
            logger.info(f"Generation complete ({elapsed:.1f}s). Response len: {len(response)}")
            
            # Save the full generated text
            output_file = LOG_DIR / f"iteration_{i+1}_output.md"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(response)
            logger.info(f"📄 Saved full response to: {output_file}")
            
            # 2. Grade
            evaluation = self.evaluator.grade_output(response, query)
            
            # Log state
            state = {
                "iteration": i,
                "score": evaluation.total_score,
                "scores": evaluation.criteria_scores,
                "weakest": evaluation.weakest_criterion,
                "feedback": evaluation.feedback,
                "timestamp": time.time()
            }
            history.append(state)
            
            # Save history incrementally
            with open(LOG_DIR / "run_history.json", "w") as f:
                json.dump(history, f, indent=2)
            
            # 3. Check Pass
            if evaluation.pass_status:
                logger.info("🎉 SUCCESS! Gold Standard Achieved.")
                break
                
            # 4. Refine
            logger.info(f"⚠️ Failed Criteria: {evaluation.weakest_criterion} (Score: {evaluation.criteria_scores.get(evaluation.weakest_criterion)})")
            
            target_file = self.refiner.identify_target_file(evaluation.weakest_criterion)
            logger.info(f"Targeting file: {target_file}")
            
            feedback_text = evaluation.feedback.get(evaluation.weakest_criterion, "Improve this.")
            patch = self.refiner.generate_patch(evaluation.weakest_criterion, feedback_text, target_file)
            
            if patch:
                logger.info("Generated Patch. Applying...")
                success = self.refiner.apply_patch(patch, target_file)
                if not success:
                    logger.error("Failed to apply patch. Stopping.")
                    break
            else:
                logger.error("Failed to generate patch. Stopping.")
                break
                
            # Pause for supervisor?
            # In headless mode, we continue.
            
        logger.info("Optimization Loop Succeeded (or reached max iterations).")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = sys.argv[1]
    else:
        query = "Generate a comprehensive review of road safety assessment techniques, comparing conflict-based vs crash-based approaches"
        
    loop = OptimizationLoop(model_name="gpt-oss:120b-cloud")
    loop.run_cycle(query)
