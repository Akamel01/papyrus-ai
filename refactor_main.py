"""Refactor main.py to use extracted UI components."""

import sys

def refactor():
    file_path = 'app/main.py'
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 1. Insert imports around line 13 (after sys.path.insert)
    # Finding the insertion point
    insert_idx = -1
    for i, line in enumerate(lines):
        if 'sys.path.insert' in line:
            insert_idx = i + 1
            break
            
    if insert_idx == -1:
        print("Could not find sys.path.insert insertion point.")
        return

    imports = [
        "\n",
        "# Import extracted UI components\n",
        "from src.ui.monitor_components import (\n",
        "    render_two_level_pills, \n",
        "    render_monitor_panel, \n",
        "    render_sub_pills_compact, \n",
        "    reset_progress_state, \n",
        "    advance_sub_pill, \n",
        "    advance_section, \n",
        "    render_progress_steps, \n",
        "    render_status_row\n",
        ")\n"
    ]
    
    # 2. Identify the block to delete (Lines 560 to 847 approx)
    # Start: def render_two_level_pills
    # End: Just before def check_clarification_needed
    
    start_delete_idx = -1
    end_delete_idx = -1
    
    for i, line in enumerate(lines):
        if 'def render_two_level_pills() -> str:' in line:
            start_delete_idx = i
        if 'def check_clarification_needed(' in line:
            end_delete_idx = i
            # We found the end, no need to continue for end
            # But we need start first
    
    if start_delete_idx == -1 or end_delete_idx == -1:
        print(f"Could not identify delete block. Start: {start_delete_idx}, End: {end_delete_idx}")
        return

    print(f"Deleting block from line {start_delete_idx+1} to {end_delete_idx}")
    
    # Construct new content
    new_lines = lines[:insert_idx] + imports + lines[insert_idx:start_delete_idx] + lines[end_delete_idx:]
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print("Refactoring complete.")

if __name__ == "__main__":
    refactor()
