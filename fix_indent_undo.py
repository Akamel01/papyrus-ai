"""Undo incorrect indentation in main.py for specific range"""

# Read the file
with open('app/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Range to fix (0-indexed in list, but we use line numbers for reference)
# Line 824 is index 823
# Line 1629 is index 1628
start_idx = 823 
end_idx = 1628

# Search for the *second* occurrence of 'depth_emoji' to confirm end_idx
occurrences = []
for i, line in enumerate(lines):
    if 'depth_emoji = {"Low":' in line:
        occurrences.append(i)

if len(occurrences) >= 2:
    print(f"Confimed occurrences at lines: {[o+1 for o in occurrences]}")
    # We want to dedent everything between the first occurrence and just before the second
    # usage context: first one is inside render_status_row, second is inside main
    
    # Actually, let's stick to the plan: dedent lines 824 to 1629
    # But verify that line 1628 (1629) is indeed the line before the second occurence?
    target_end = occurrences[1] - 1
    print(f"Target dedent end index: {target_end} (Line {target_end+1})")
else:
    print("WARNING: Could not find two occurrences of depth_emoji. Proceeding with caution.")
    target_end = 1628

# Dedent lines in range
fixed_lines = []
for i, line in enumerate(lines):
    if i >= start_idx and i <= target_end:
        if line.startswith('    '):
            fixed_lines.append(line[4:])
        else:
            # If line effectively doesn't have 4 spaces, keep as is (shouldn't happen for valid code)
            fixed_lines.append(line)
    else:
        fixed_lines.append(line)

# Write back
with open('app/main.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print(f"Dedented lines {start_idx+1} to {target_end+1}")
