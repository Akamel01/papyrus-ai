"""
SME Research Assistant - Reranker

Cross-encoder reranking for improved retrieval quality.
Supports local CrossEncoder (sentence-transformers) and remote Ollama-based reranking.
"""

import json
import logging
import time
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from src.core.interfaces import Reranker, RetrievalResult
from src.core.exceptions import RerankerError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Qwen3-Reranker prompt templates
# ─────────────────────────────────────────────────────────────
RERANKER_SYSTEM_PROMPT = (
    "You are a relevance scoring engine. "
    "Given a Query and a Document, judge how relevant the Document is to the Query. "
    "Return ONLY a JSON object with a single key 'score' whose value is a float "
    "between 0.0 (completely irrelevant) and 1.0 (perfectly relevant). "
    'Example: {"score": 0.85}'
)

RERANKER_USER_TEMPLATE = (
    "<Instruct>: Given a research query, judge the relevance of the document.\n"
    "<Query>: {query}\n"
    "<Document>: {document}"
)


class OllamaReranker(Reranker):
    """
    Reranker that delegates to an Ollama service via /api/chat.

    Uses Qwen3-Reranker (a generative cross-encoder) running on GPU inside
    the sme_ollama container. Scores each (query, document) pair in parallel
    using ThreadPoolExecutor for maximum throughput.
    """

    def __init__(
        self,
        model_name: str = "dengcao/Qwen3-Reranker-0.6B:Q8_0",
        base_url: str = "http://sme_ollama:11434",
        max_parallel: int = 128,
        timeout: int = 60,
        max_doc_chars: int = 4000,
    ):
        """
        Args:
            model_name: Ollama model identifier
            base_url: Ollama API URL (inside Docker network)
            max_parallel: Max concurrent scoring requests (match OLLAMA_NUM_PARALLEL)
            timeout: Per-request timeout in seconds
            max_doc_chars: Truncate document text beyond this length
        """
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.max_parallel = max_parallel
        self.timeout = timeout
        self.max_doc_chars = max_doc_chars
        self._client: Optional[httpx.Client] = None

        logger.info(
            f"OllamaReranker initialized: model={model_name}, "
            f"url={base_url}, max_parallel={max_parallel}"
        )

    def _get_client(self) -> httpx.Client:
        """Lazy-create persistent HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                limits=httpx.Limits(
                    max_connections=self.max_parallel + 10,
                    max_keepalive_connections=self.max_parallel,
                ),
            )
        return self._client

    def load(self):
        """
        Ensure model is available on Ollama and pre-warm it into GPU memory.
        """
        logger.info(f"OllamaReranker.load() — checking model '{self.model_name}'...")
        client = self._get_client()

        # Check if model exists
        try:
            response = client.get("/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                exists = any(
                    m.get("name", "").startswith(self.model_name.split(":")[0])
                    for m in models
                )
                if exists:
                    logger.info(f"✅ Reranker model '{self.model_name}' found on Ollama.")
                else:
                    logger.warning(
                        f"⚠️ Reranker model '{self.model_name}' not found. Pulling..."
                    )
                    self._pull_model()
        except Exception as e:
            logger.error(f"Failed to check Ollama models: {e}")
            raise RerankerError(f"Cannot connect to Ollama at {self.base_url}: {e}")

        # Pre-warm: send a dummy request to load model into GPU memory
        try:
            logger.info("Pre-warming reranker model into GPU memory...")
            warmup_score = self._score_pair("warmup query", "warmup document")
            logger.info(
                f"✅ Reranker pre-warmed successfully (warmup score: {warmup_score:.3f})"
            )
        except Exception as e:
            logger.error(f"Reranker pre-warm failed: {e}")
            raise RerankerError(f"Reranker pre-warm failed: {e}")

        return self

    def _pull_model(self):
        """Pull reranker model into Ollama."""
        logger.info(f"Pulling reranker model: {self.model_name}...")
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"model": self.model_name},
                timeout=None,
            ) as r:
                for line in r.iter_lines():
                    pass
            logger.info("Reranker model pull complete.")
        except Exception as e:
            logger.error(f"Reranker model pull failed: {e}")
            raise RerankerError(f"Failed to pull reranker model: {e}")

    def _score_pair(self, query: str, document: str) -> float:
        """
        Score a single (query, document) pair via Ollama /api/chat.

        Returns a float score between 0.0 and 1.0.
        Falls back to 0.0 on parse failure.
        """
        # Truncate long documents to stay within context window
        doc_text = document[: self.max_doc_chars] if len(document) > self.max_doc_chars else document

        user_prompt = RERANKER_USER_TEMPLATE.format(query=query, document=doc_text)

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": RERANKER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": "60m",
            "options": {
                "num_predict": 20,
                "temperature": 0,
                "num_ctx": 1024,
            },
        }

        client = self._get_client()
        response = client.post("/api/chat", json=payload)

        if response.status_code != 200:
            logger.warning(
                f"Ollama reranker returned {response.status_code}: "
                f"{response.text[:200]}"
            )
            return 0.0

        try:
            data = response.json()
            content = data.get("message", {}).get("content", "{}")
            parsed = json.loads(content)
            score = float(parsed.get("score", 0.0))
            # Clamp to [0, 1]
            return max(0.0, min(1.0, score))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse reranker score: {e} — content: {content[:100]}")
            return 0.0

    def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """
        Rerank results using Qwen3-Reranker via Ollama.

        Sends parallel scoring requests via ThreadPoolExecutor.

        Args:
            query: Original query
            results: Results to rerank
            top_k: Number of results to return

        Returns:
            Reranked results sorted by relevance score
        """
        if not results:
            return []

        if len(results) <= 1:
            return results[:top_k]

        t0 = time.perf_counter()
        n = len(results)
        scores = [0.0] * n

        logger.info(
            f"[RERANK] Scoring {n} candidates via Ollama "
            f"(max_parallel={self.max_parallel})..."
        )

        # Parallel scoring via ThreadPoolExecutor
        with ThreadPoolExecutor(
            max_workers=min(self.max_parallel, n)
        ) as pool:
            future_to_idx = {
                pool.submit(self._score_pair, query, r.chunk.text): i
                for i, r in enumerate(results)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    scores[idx] = future.result()
                except Exception as e:
                    logger.warning(f"[RERANK] Scoring failed for candidate {idx}: {e}")
                    scores[idx] = 0.0

        elapsed = time.perf_counter() - t0

        # Build reranked results
        reranked = []
        for result, score in zip(results, scores):
            reranked.append(
                RetrievalResult(
                    chunk=result.chunk,
                    score=score,
                    source="reranked",
                    metadata={
                        **result.metadata,
                        "original_score": result.score,
                        "original_source": result.source,
                    },
                )
            )

        reranked.sort(key=lambda x: x.score, reverse=True)

        # Log summary
        top_scores = [f"{r.score:.3f}" for r in reranked[:5]]
        logger.info(
            f"[RERANK] ✅ {n} candidates scored in {elapsed:.2f}s "
            f"(top-5 scores: {top_scores})"
        )

        return reranked[:top_k]

    def __del__(self):
        """Clean up HTTP client."""
        try:
            if self._client and not self._client.is_closed:
                self._client.close()
        except Exception:
            pass


class CrossEncoderReranker(Reranker):
    """
    Reranker using HuggingFace Cross-Encoder models.
    """
    
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cuda",
        batch_size: int = 128,
        max_length: int = 512,
        dtype: Optional[str] = None
    ):
        """
        Initialize reranker.
        
        Args:
            model_name: Cross-encoder model name
            device: Device to use
            batch_size: Batch size for reranking
            max_length: Max sequence length
            dtype: Specific dtype (e.g. "fp16", "fp32")
        """
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.dtype_str = dtype
        self._model = None
    
    def load(self):
        """Eagerly load the model into memory."""
        logger.info(f"CrossEncoderReranker.load() called [ID: {id(self)}]. Model: {self.model_name}")
        self._load_model()
        return self

    def _load_model(self):
        """Lazy load the model."""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            import torch
            
            if self.device == "cuda" and not torch.cuda.is_available():
                msg = "CUDA requested for Reranker but not available. CPU usage is strictly forbidden."
                logger.error(msg)
                raise RerankerError(msg)
            
            # Determine dtype
            if self.dtype_str == "fp16":
                dtype = torch.float16
            elif self.dtype_str == "fp32":
                dtype = torch.float32
            else:
                dtype = torch.float16 if self.device == "cuda" else torch.float32
            
            logger.info(f"Loading reranker model: {self.model_name} on {self.device} (dtype: {dtype}, max_length: {self.max_length})")
            self._model = CrossEncoder(
                self.model_name,
                device=self.device,
                trust_remote_code=True,
                max_length=self.max_length,
                automodel_args={
                    "low_cpu_mem_usage": True,
                    "torch_dtype": dtype
                }
            )
            logger.info(f"Reranker loaded on {self.device}")
    
    def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 10
    ) -> List[RetrievalResult]:
        """
        Rerank results using cross-encoder.
        """
        if not results:
            return []
        
        if len(results) <= 1:
            return results[:top_k]
        
        self._load_model()
        
        if self._model == "NOOP":
            logger.warning("Reranker unavailable, returning original order")
            return results[:top_k]
        
        try:
            pairs = [[query, r.chunk.text] for r in results]
            
            import torch
            with torch.inference_mode():
                scores = self._model.predict(
                    pairs,
                    batch_size=self.batch_size,
                    show_progress_bar=len(pairs) > 50
                )
            
            if self.device == "cuda":
                # Clear large transient allocations after the entire forward pass loop
                torch.cuda.empty_cache()
            
            reranked = []
            for result, score in zip(results, scores):
                reranked.append(RetrievalResult(
                    chunk=result.chunk,
                    score=float(score),
                    source="reranked",
                    metadata={
                        **result.metadata,
                        "original_score": result.score,
                        "original_source": result.source
                    }
                ))
            
            reranked.sort(key=lambda x: x.score, reverse=True)
            return reranked[:top_k]
            
        except Exception as e:
            logger.warning(f"Reranking failed, returning original order: {e}")
            return results[:top_k]


class NoOpReranker(Reranker):
    """Reranker that does nothing (passthrough)."""
    
    def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 10
    ) -> List[RetrievalResult]:
        """Return results unchanged."""
        return results[:top_k]


def create_reranker(
    model_name: str = "BAAI/bge-reranker-v2-m3",
    device: str = "cuda",
    enabled: bool = True,
    remote_url: Optional[str] = None,
    max_parallel: int = 128,
    batch_size: int = 128,
    max_length: int = 512,
    dtype: Optional[str] = None,
) -> Reranker:
    """
    Factory function to create a reranker.

    Args:
        model_name: Model name/identifier
        device: Device for local CrossEncoder (ignored for Ollama)
        enabled: Whether reranking is enabled
        remote_url: If provided, use OllamaReranker via this URL
        max_parallel: Max concurrent requests for OllamaReranker
        batch_size: Batch size for CrossEncoderReranker
        max_length: Max sequence length for CrossEncoderReranker
        dtype: Dtype for CrossEncoderReranker ("fp16", "fp32")
    """
    if not enabled:
        return NoOpReranker()

    if remote_url:
        logger.info(
            f"Creating OllamaReranker: model={model_name}, url={remote_url}"
        )
        return OllamaReranker(
            model_name=model_name,
            base_url=remote_url,
            max_parallel=max_parallel,
        )

    return CrossEncoderReranker(
        model_name=model_name,
        device=device,
        batch_size=batch_size,
        max_length=max_length,
        dtype=dtype,
    )
