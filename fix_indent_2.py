"""Fix indentation for assistant message block in main.py"""

# Read the file
with open('app/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the start line: depth_emoji definition
start_idx = None
for i, line in enumerate(lines):
    if 'depth_emoji = {"Low":' in line:
        start_idx = i
        print(f"Found block start at line {i+1}")
        break

if start_idx is None:
    print("ERROR: Could not find block start")
    exit(1)

# Find the end of main() function
end_idx = None
for i in range(start_idx, len(lines)):
    line = lines[i]
    if 'if __name__ == "__main__":' in line:
        end_idx = i - 1
        print(f"Found block end at line {i}")
        break

if end_idx is None:
    end_idx = len(lines)

# Add 4 spaces to all lines in range
fixed_lines = []
for i, line in enumerate(lines):
    if i >= start_idx and i <= end_idx:
        if line.strip(): # Only indent non-empty lines
            fixed_lines.append('    ' + line)
        else:
            fixed_lines.append(line)
    else:
        fixed_lines.append(line)

# Write back
with open('app/main.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print(f"Fixed indentation from line {start_idx+1} to {end_idx+1}")
