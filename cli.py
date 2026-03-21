#!/usr/bin/env python
"""
SME Research Assistant - Command Line Interface

CLI for querying the RAG system and managing papers.
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_query(args):
    """Query the RAG system."""
    from src.utils.helpers import load_config
    from src.retrieval import create_hybrid_search, create_reranker, create_context_builder
    from src.generation import create_ollama_client, create_prompt_builder
    from src.indexing import create_bm25_index
    
    print("Loading RAG pipeline...")
    config = load_config("config/config.yaml")
    
    # Load BM25 index
    bm25_index = create_bm25_index()
    if not bm25_index.load():
        print("Warning: BM25 index not found. Run ingestion first.")
    
    # Create components
    hybrid_search = create_hybrid_search(config)
    reranker = create_reranker(enabled=args.rerank)
    context_builder = create_context_builder()
    llm = create_ollama_client(
        model_name=config.get("generation", {}).get("model_name", "qwen2.5:14b-instruct-q4_K_M")
    )
    prompt_builder = create_prompt_builder()
    
    print(f"\nQuery: {args.query}\n")
    print("Searching...")
    
    # Search
    results = hybrid_search.search(args.query, top_k=50)
    print(f"Found {len(results)} initial results")
    
    if not results:
        print("No results found.")
        return
    
    # Rerank
    if args.rerank:
        print("Reranking...")
        results = reranker.rerank(args.query, results, top_k=10)
    
    # Build context
    context, used_results = context_builder.build_context(results[:10])
    print(f"Using {len(used_results)} chunks for context")
    
    # Show sources if requested
    if args.show_sources:
        print("\nSources:")
        for i, r in enumerate(used_results[:5]):
            print(f"  {i+1}. [{r.chunk.doi}] - {r.chunk.section} (score: {r.score:.3f})")
    
    # Generate response
    print("\nGenerating response...")
    prompt = prompt_builder.build_rag_prompt(args.query, context)
    
    if args.stream:
        print("\nResponse:")
        print("-" * 50)
        for token in llm.generate_stream(prompt, prompt_builder.system_prompt):
            print(token, end="", flush=True)
        print("\n" + "-" * 50)
    else:
        response = llm.generate(prompt, prompt_builder.system_prompt)
        print("\nResponse:")
        print("-" * 50)
        print(response)
        print("-" * 50)


def cmd_ingest(args):
    """Ingest papers into the system."""
    from scripts.ingest_papers import PaperIngester
    from src.utils.helpers import load_config
    
    try:
        config = load_config("config/config.yaml")
    except:
        config = {}
    
    ingester = PaperIngester(config)
    stats = ingester.ingest_papers(
        papers_dir=args.papers_dir,
        limit=args.limit
    )
    
    print(f"\nIngestion complete:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Chunks: {stats['chunks_created']}")


def cmd_stats(args):
    """Show system statistics."""
    from src.indexing import create_vector_store, create_bm25_index
    
    print("System Statistics")
    print("=" * 40)
    
    # Vector store
    try:
        vs = create_vector_store()
        stats = vs.get_stats()
        print(f"\nVector Store (Qdrant):")
        print(f"  Chunks: {stats.get('points_count', 'N/A')}")
        print(f"  Status: {stats.get('status', 'N/A')}")
    except Exception as e:
        print(f"\nVector Store: Error - {e}")
    
    # BM25
    try:
        bm25 = create_bm25_index()
        if bm25.load():
            print(f"\nBM25 Index:")
            print(f"  Chunks: {bm25.count()}")
        else:
            print(f"\nBM25 Index: Not found")
    except Exception as e:
        print(f"\nBM25 Index: Error - {e}")
    
    # Ollama
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            print(f"\nOllama:")
            print(f"  Status: Running")
            print(f"  Models: {len(models)}")
            for m in models[:5]:
                print(f"    - {m.get('name', 'unknown')}")
    except:
        print(f"\nOllama: Not running")


def main():
    parser = argparse.ArgumentParser(
        description="SME Research Assistant CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Query command
    query_parser = subparsers.add_parser("query", help="Query the RAG system")
    query_parser.add_argument("query", help="Question to ask")
    query_parser.add_argument("--no-rerank", dest="rerank", action="store_false",
                              help="Skip reranking")
    query_parser.add_argument("--show-sources", action="store_true",
                              help="Show source documents")
    query_parser.add_argument("--stream", action="store_true",
                              help="Stream response tokens")
    
    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest papers")
    ingest_parser.add_argument("--papers-dir", default="DataBase/Papers",
                               help="Papers directory")
    ingest_parser.add_argument("--limit", type=int, default=None,
                               help="Limit number of papers")
    
    # Stats command
    subparsers.add_parser("stats", help="Show system statistics")
    
    args = parser.parse_args()
    
    if args.command == "query":
        cmd_query(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
