"""Fix indentation for query processing block in main.py"""

# Read the file
with open('app/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "if prompt := st.chat_input"
prompt_line_idx = None
for i, line in enumerate(lines):
    if 'if prompt := st.chat_input' in line:
        prompt_line_idx = i
        print(f"Found 'if prompt' at line {i+1}")
        break

if prompt_line_idx is None:
    print("ERROR: Could not find 'if prompt := st.chat_input' line")
    exit(1)

# Find where the if block should end (look for next same-level or lower indentation)
prompt_indent = len(lines[prompt_line_idx]) - len(lines[prompt_line_idx].lstrip())
print(f"Prompt line indentation: {prompt_indent} spaces")

# Find the end of the main() function
end_idx = None
for i in range(prompt_line_idx + 1, len(lines)):
    line = lines[i]
    if line.strip() and not line.strip().startswith('#'):
        current_indent = len(line) - len(line.lstrip())
        # If we find a line with same or less indentation as 'if prompt', that's where block ends
        if current_indent <= prompt_line_idx and 'if __name__' in line:
            end_idx = i
            print(f"Found end of main() at line {i+1}")
            break

# Add 4 spaces to all lines between prompt_line and end (except the prompt line itself)
fixed_lines = []
for i, line in enumerate(lines):
    if i <= prompt_line_idx or i >= end_idx:
        # Keep original
        fixed_lines.append(line)
    else:
        # Check if line needs more indentation
        if line.strip():  # Non-empty line
            current_indent = len(line) - len(line.lstrip())
            # Only add indent if not already properly indented (should be at least prompt_indent + 4)
            if current_indent < prompt_indent + 4:
                fixed_lines.append('    ' + line)  # Add 4 spaces
            else:
                fixed_lines.append(line)
        else:
            # Empty line, keep as is
            fixed_lines.append(line)

# Write back
with open('app/main.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print(f"Fixed indentation from line {prompt_line_idx+2} to line {end_idx}")
