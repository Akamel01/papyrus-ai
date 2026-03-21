"""
SME Research Assistant - Coverage Manager

Handles state tracking for discovery coverage to enable efficient, 
gap-aware incremental updates.
"""

import json
import logging
import hashlib
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Type alias for a Time Interval [StartYear, EndYear]
TimeInterval = Tuple[int, int]


class CoverageManager:
    """
    Manages the 'Discovery Coverage Map'.
    
    Tracks which (Search Signature -> Time Intervals) have been fully scanned.
    Calculates gaps between finding requirements and current state.
    """
    
    def __init__(self, state_file: str = "data/discovery_coverage.json"):
        self.state_file = Path(state_file)
        self.coverage_map: Dict[str, List[TimeInterval]] = {}
        self._load_state()

    def _load_state(self):
        """Load coverage map from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert lists back to tuples if needed (JSON uses lists)
                    self.coverage_map = {
                        k: [tuple(interval) for interval in v] 
                        for k, v in data.get("signatures", {}).items()
                    }
                logger.info(f"Loaded coverage map with {len(self.coverage_map)} signatures")
            except Exception as e:
                logger.error(f"Failed to load coverage state: {e}")
                self.coverage_map = {}
        else:
            logger.info("No existing coverage state found. Starting fresh.")
            self.coverage_map = {}

    def save_state(self):
        """Persist coverage map to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "updated_at": datetime.now().isoformat(),
                "signatures": self.coverage_map
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug("Saved coverage state")
        except Exception as e:
            logger.error(f"Failed to save coverage state: {e}")

    def generate_signature(self, source: str, keyword: str, filters: Dict[str, Any]) -> str:
        """
        Generate a unique signature for a specific search configuration.
        excludes continuous variables like 'min_year', 'max_year'.
        includes discrete variables like 'type', 'open_access'.
        """
        # Normalize inputs
        norm_source = source.lower().strip()
        norm_keyword = keyword.lower().strip()
        
        # Extract discrete filters (add more as needed)
        # Note: We do NOT include min_year/max_year here, as they are the continuous dimension
        filter_keys = sorted([k for k in filters.keys() if k not in ['min_year', 'max_year', 'from_updated_date']])
        
        filter_str_parts = []
        for k in filter_keys:
            val = filters[k]
            # Handle list values (e.g. types)
            if isinstance(val, list):
                val = sorted([str(v).lower() for v in val])
                val_str = "|".join(val)
            else:
                val_str = str(val).lower()
            filter_str_parts.append(f"{k}:{val_str}")
            
        filter_sig = "|".join(filter_str_parts)
        
        # Construct raw string
        raw_sig = f"source:{norm_source}|kw:{norm_keyword}|{filter_sig}"
        
        # Hash it for consistent length
        return hashlib.md5(raw_sig.encode()).hexdigest()

    def calculate_gaps(self, signature: str, target_interval: TimeInterval) -> List[TimeInterval]:
        """
        Compute the missing time intervals (Gaps) by subtracting 
        current coverage from the target interval.
        
        Args:
            signature: The search signature
            target_interval: Tuple (min_year, max_year)
            
        Returns:
            List of disjoint intervals representing gaps to fetch.
        """
        target_start, target_end = target_interval
        covered_intervals = self.coverage_map.get(signature, [])
        
        # Sort covered intervals
        covered_intervals = sorted(covered_intervals, key=lambda x: x[0])
        
        gaps = []
        current_pointer = target_start
        
        for (cov_start, cov_end) in covered_intervals:
            # Case 1: Covered interval is completely before current need
            # [Cov] ... [Target]
            if cov_end < current_pointer:
                continue
                
            # Case 2: Covered interval starts after current pointer
            # [Target_Start] ... G A P ... [Cov_Start]
            if cov_start > current_pointer:
                # We have a gap from pointer to start of coverage
                gap_end = min(cov_start - 1, target_end)
                if gap_end >= current_pointer:
                    gaps.append((current_pointer, gap_end))
                
                # Move pointer to end of this coverage
                current_pointer = cov_end + 1
            else:
                # Case 3: Overlap
                # Move pointer to end of coverage
                current_pointer = max(current_pointer, cov_end + 1)
            
            # Optimization: If pointer exceeded target, we are done
            if current_pointer > target_end:
                break
                
        # Final Gap: If reference coverage ended before target ended
        if current_pointer <= target_end:
            gaps.append((current_pointer, target_end))
            
        return gaps

    def mark_covered(self, signature: str, interval: TimeInterval):
        """
        Mark a specific interval as covered for a signature.
        Automatically merges adjacent or overlapping intervals.
        """
        if signature not in self.coverage_map:
            self.coverage_map[signature] = []
            
        current_intervals = self.coverage_map[signature]
        current_intervals.append(interval)
        
        # Merge Logic
        # 1. Sort by start time
        current_intervals.sort(key=lambda x: x[0])
        
        merged = []
        if not current_intervals:
            self.coverage_map[signature] = []
            self.save_state()
            return

        # Start with first interval
        prev_start, prev_end = current_intervals[0]
        
        for i in range(1, len(current_intervals)):
            curr_start, curr_end = current_intervals[i]
            
            # If current starts <= previous end + 1 (adjacent or overlapping)
            if curr_start <= prev_end + 1:
                # Merge: Extend previous end if needed
                prev_end = max(prev_end, curr_end)
            else:
                # No overlap, push previous and start new
                merged.append((prev_start, prev_end))
                prev_start, prev_end = curr_start, curr_end
                
        # Append the last one
        merged.append((prev_start, prev_end))
        
        self.coverage_map[signature] = merged
        self.save_state()

    def get_freshness_gap(self, signature: str, current_year: int) -> bool:
        """
        Check if we need a 'Freshness' update (checking recently updated papers).
        This is a simplification: currently we just return True if we have ANY coverage,
        implying we should check for updates to that coverage.
        """
        return signature in self.coverage_map
