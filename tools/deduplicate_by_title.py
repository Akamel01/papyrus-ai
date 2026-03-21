import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = Path("sme.db")

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def score_paper(paper: Dict[str, Any]) -> int:
    score = 0
    if paper.get('pdf_path'):
        score += 100
    if paper.get('doi'):
        score += 20
    if paper.get('abstract') and len(paper['abstract']) > 50:
        score += 10
    if paper.get('authors') and len(paper['authors']) > 5:
        score += 5
    # Prefer recently updated?
    # if paper.get('updated_at'): score += 1
    return score

def deduplicate():
    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        return

    logger.info("Loading all papers into memory (Optimization)...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM papers")
        all_papers = cursor.fetchall()
        logger.info(f"Loaded {len(all_papers)} papers.")

        # Group by Lower Title
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for p in all_papers:
            if p.get('title'):
                groups[p['title'].lower()].append(p)
        
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}
        logger.info(f"Found {len(duplicates)} duplicate groups.")

        merged_cnt = 0
        deleted_ids = []
        updates = [] # List of (sql, params)

        print("Processing duplicates...")
        
        for title, rows in duplicates.items():
            # Sort by Score (Survivor first)
            ranked = sorted(rows, key=score_paper, reverse=True)
            survivor = ranked[0]
            victims = ranked[1:]
            
            # Merge Metadata
            fields_to_merge = ['doi', 'abstract', 'authors', 'year', 'venue', 'url', 'created_at']
            current_updates = {}
            
            for v in victims:
                deleted_ids.append(v['id'])
                for field in fields_to_merge:
                    if not survivor.get(field) and v.get(field):
                        survivor[field] = v[field]
                        current_updates[field] = v[field]
            
            if current_updates:
                # Prepare Update SQL
                set_clause = ", ".join([f"{k} = ?" for k in current_updates.keys()])
                params = list(current_updates.values())
                params.append(survivor['id'])
                updates.append((f"UPDATE papers SET {set_clause} WHERE id = ?", params))
                merged_cnt += 1

        logger.info(f"Applying changes: Deleting {len(deleted_ids)} records, Updating {len(updates)} records...")
        
        # Batch Execution
        if deleted_ids:
            # Delete in chunks
            chunk_size = 900
            for i in range(0, len(deleted_ids), chunk_size):
                chunk = deleted_ids[i:i+chunk_size]
                placeholders = ','.join(['?'] * len(chunk))
                cursor.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", chunk)
        
        for sql, params in updates:
            cursor.execute(sql, params)
        
        conn.commit()
        logger.info("Deduplication Complete!")

    except Exception as e:
        logger.error(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    deduplicate()
