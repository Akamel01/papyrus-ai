"""Patch main.py to fix UI update calls."""

import re

def fix_ui_calls():
    file_path = 'app/main.py'
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update on_step_update callback to REFRESH UI
    # We find the function definition and replace it
    on_step_pattern = r'def on_step_update\(step_data\):.*?break'
    on_step_replacement = """def on_step_update(step_data):
                                \"\"\"Callback for live monitoring updates with pill advancement.\"\"\"
                                st.session_state.live_steps.append(step_data)
                                st.session_state.monitor_steps.append(step_data)
                            
                                # Map step to pill progress
                                step_name = step_data.get("name", "")
                                try:
                                    from src.config.progress_config import get_step_to_subpill_mapping
                                    mapping = get_step_to_subpill_mapping(st.session_state.progress_config)
                            
                                    # Try to find this step in mapping (case-insensitive)
                                    found = False
                                    for key, (main_idx, sub_idx) in mapping.items():
                                        if key.lower() in step_name.lower() or step_name.lower() in key.lower():
                                            st.session_state.current_main_pill = main_idx
                                            st.session_state.current_sub_pill = sub_idx + 1  # Mark as completed
                                            found = True
                                            break
                                    
                                    # REFRESH UI ELEMENTS
                                    # 1. Monitor Panel (Right)
                                    if "_monitor_col" in st.session_state:
                                        with st.session_state._monitor_col:
                                            render_monitor_panel()
                                    
                                    # 2. Status Pills (Main)
                                    # We can't access status_placeholder directly if it's not global/passed.
                                    # But we can try to rely on next rerun or use st.empty() if needed.
                                    # Ideally placeholders are passed or global.
                                    # For now, Monitor Panel is crucial right-side.
                                except Exception as e:
                                    print(f"Error in on_step_update: {e}")"""
    
    # Actually regex replacement for multi-line is tricky.
    # I'll use a simpler replacement for the manual blocks first.
    
    # Block 1: Analyzing query
    content = content.replace(
        'status_placeholder.markdown(\n                    render_status_row(cfg[\'depth\'], seq_indicator, cfg[\'model\'], 0, total_steps, "Analyzing query..."),\n                    unsafe_allow_html=True\n                )',
        'st.session_state.current_main_pill = 0\n                st.session_state.current_sub_pill = 0\n                status_placeholder.markdown(render_two_level_pills(), unsafe_allow_html=True)\n                if "_monitor_col" in st.session_state:\n                    with st.session_state._monitor_col:\n                        render_monitor_panel()'
    )

    # Block 2: Searching
    # Use generic regex replace for render_status_row calls
    # Pattern: status_placeholder.markdown(\n\s*render_status_row\(.*?\),\n\s*unsafe_allow_html=True\n\s*\)
    
    pattern = r'status_placeholder\.markdown\(\s*render_status_row\(.*?\),\s*unsafe_allow_html=True\s*\)'
    
    def replacer(match):
        # We replace with the update logic. 
        # But we need to know WHICH step to set.
        # It's hard to infer step from regex.
        # Fallback: Just call render_two_level_pills() and let state persist?
        # No, we need to set state.
        
        # So manual string replace is safer.
        return match.group(0) # No-op for regex, do manual below.

    # Manual replacements
    # Step 1 Searching
    content = content.replace(
        'render_status_row(cfg[\'depth\'], seq_indicator, cfg[\'model\'], 1, total_steps, f"Searching {actual_paper_range[1]} papers...")',
        'render_two_level_pills()' 
    )
    # Wait, render_status_row returns HTML. render_two_level_pills() returns HTML.
    # But I also need to UPDATE STATE.
    # I'll insert state updates line by line.
    
    # 1391: 0, "Analyzing check" -> already done above?
    
    # 1397: 1, "Searching..."
    # Previous line: progress_placeholder.markdown(...)
    # I will insert state update before progress_placeholder.
    content = content.replace(
        '# Step 2: Searching (step 1)',
        '# Step 2: Searching (step 1)\n                st.session_state.current_main_pill = 0\n                '
    )
    
    # 1572: Reranking
    content = content.replace(
        '# Step 3: Reranking',
        '# Step 3: Reranking\n                    st.session_state.current_main_pill = 0\n                    st.session_state.current_sub_pill = 1 # Rerank\n                    if "_monitor_col" in st.session_state:\n                        with st.session_state._monitor_col:\n                            render_monitor_panel()'
    )
    
    # 1584: Generating
    content = content.replace(
        '# Step 4: Generating',
        '# Step 4: Generating\n                st.session_state.current_main_pill = 1\n                st.session_state.current_sub_pill = 0\n                if "_monitor_col" in st.session_state:\n                    with st.session_state._monitor_col:\n                        render_monitor_panel()'
    )
    
    # 1591: Validating
    content = content.replace(
        '# Step 5: Validating',
        '# Step 5: Validating\n                st.session_state.current_main_pill = 2\n                st.session_state.current_sub_pill = 0\n                if "_monitor_col" in st.session_state:\n                    with st.session_state._monitor_col:\n                        render_monitor_panel()'
    )

    # Finally replace ALL render_status_row calls with render_two_level_pills
    content = re.sub(r'render_status_row\(.*?\)', 'render_two_level_pills()', content, flags=re.DOTALL)
    
    # And fix the on_step_update logic
    # We'll use a specific unique string to target the function body inner loop
    content = content.replace(
        'st.session_state.current_sub_pill = sub_idx + 1  # Mark as completed\n                                        break',
        'st.session_state.current_sub_pill = sub_idx + 1  # Mark as completed\n                                        break\n                                    \n                                    # Refresh Monitor Panel\n                                    if "_monitor_col" in st.session_state:\n                                        with st.session_state._monitor_col:\n                                            render_monitor_panel()'
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("UI calls patched.")

if __name__ == "__main__":
    fix_ui_calls()
