"""Patch main.py to use monitor_placeholder for panel refreshes."""

import re

def fix_ui_v2():
    file_path = 'app/main.py'
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match the blocks injected by fix_ui_calls.py
    # They look like:
    # if "_monitor_col" in st.session_state:
    #    with st.session_state._monitor_col:
    #        render_monitor_panel()
    
    # We use flexible regex for whitespace
    pattern = r'if\s+"_monitor_col"\s+in\s+st\.session_state:\s+with\s+st\.session_state\._monitor_col:\s+render_monitor_panel\(\)'
    
    replacement = 'if "monitor_placeholder" in st.session_state:\n                        render_monitor_panel(st.session_state.monitor_placeholder)'

    # We need to be careful with indentation.
    # The pattern matches the code, but indentation varies.
    # regex should capture indentation?
    
    # Better approach: Match the core lines regardless of indentation, and try to preserve it?
    # Or just simple string replace if we know indentation?
    # fix_ui_calls.py used specific indentations.
    
    # Let's try to match line-by-line using re.sub with function to handle indent.
    
    def replacer(match):
        # match.group(0) is the whole block.
        # We want to replace it with the new call, preserving leading indent of the first line.
        original = match.group(0)
        # Find indentation of first line
        indent = re.match(r'^\s*', original).group(0)
        # Construct new block
        # indent + if "monitor_placeholder" in st.session_state:
        # indent +     render_monitor_panel(st.session_state.monitor_placeholder)
        
        # Actually simplest is just:
        # indent + render_monitor_panel(st.session_state.monitor_placeholder)
        # Because we initialized it, we can assume it exists? 
        # But checking is safer.
        
        new_block = f'{indent}if "monitor_placeholder" in st.session_state:\n{indent}    render_monitor_panel(st.session_state.monitor_placeholder)'
        return new_block

    # Improved pattern that handles multiline match with whitespace
    # \s+ matches newlines and spaces.
    regex = r'(\s*)if\s+"_monitor_col"\s+in\s+st\.session_state:\s*\n\s*with\s+st\.session_state\._monitor_col:\s*\n\s*render_monitor_panel\(\)'
    
    # Replace
    new_content = re.sub(regex, replacer, content)
    
    # Check if changes happened
    if new_content != content:
        print("Patched repeated UI calls.")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    else:
        print("No patterns found to patch (or already patched).")

if __name__ == "__main__":
    fix_ui_v2()
