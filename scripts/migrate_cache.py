
import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

def migrate_cache():
    cache_path = Path("data/discovery_cache.json")
    old_papers_dir = Path("DataBase/Papers")
    
    if not cache_path.exists():
        logger.info("No cache file found to migrate.")
        return

    logger.info(f"Loading cache from {cache_path}")
    with open(cache_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    papers = data.get("papers", [])
    updated_count = 0
    embedded_count = 0
    
    logger.info(f"Found {len(papers)} papers. Checking against {old_papers_dir}...")
    
    for paper in papers:
        # Check if already migrated
        if "status" in paper:
            continue
            
        updated_count += 1
        
        # Check if file exists in old folder
        # We need to guess the filename or check the DOI
        # Common pattern: DOI with / replaced by _
        doi_filename = ""
        if paper.get("doi"):
            doi_filename = paper["doi"].replace("/", "_") + ".pdf"
        
        # Check for exact matches if possible
        # Since we don't have the original filename preserved in old cache schema,
        # we try our best.
        
        is_legacy = False
        if doi_filename and (old_papers_dir / doi_filename).exists():
            is_legacy = True
        
        if is_legacy:
            paper["status"] = "embedded"
            paper["pdf_path"] = str(old_papers_dir / doi_filename)
            embedded_count += 1
        else:
            paper["status"] = "discovered"
            paper["pdf_path"] = None
            
        paper["chunk_file"] = None

    logger.info(f"Migrated {updated_count} papers.")
    logger.info(f"Marked {embedded_count} as 'embedded' (found in legacy folder).")
    logger.info(f"Marked {updated_count - embedded_count} as 'discovered'.")
    
    # Backup original
    backup_path = cache_path.with_suffix(".json.bak")
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    logger.info(f"Backup saved to {backup_path}")
    
    # Save new
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    logger.info("Migration complete.")

if __name__ == "__main__":
    migrate_cache()
