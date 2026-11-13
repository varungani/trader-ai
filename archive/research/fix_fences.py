import re

for fname in ['README.md', 'TRADER_AI_ARCHITECTURE_AND_TECHNICALS.md']:
    with open(fname, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    new_lines = []
    for line in lines:
        s = line.strip()
        # If line starts with 2 backticks and not 3:
        if s.startswith('``') and not s.startswith('```'):
            line = '```' + line.lstrip('`')
        elif s.startswith('````'):
            # Strip extra backticks down to exactly 3
            idx = 0
            while idx < len(line) and line[idx] == '`':
                idx += 1
            line = '```' + line[idx:]
        new_lines.append(line)
    with open(fname, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f'Cleaned fences in {fname}')

for fname in ['README.md', 'TRADER_AI_ARCHITECTURE_AND_TECHNICALS.md']:
    with open(fname, 'r', encoding='utf-8') as f:
        text = f.read()
    # Check all lines starting with `
    lines = text.splitlines()
    fences = [l for l in lines if l.strip().startswith('`')]
    print(f'\nFences in {fname}:')
    for f_line in fences:
        if f_line.strip().startswith('```'):
            if f_line.strip().startswith('````'):
                print('  ERROR 4+ backticks:', f_line)
        elif f_line.strip().startswith('`') and len(f_line.strip()) > 3 and not f_line.strip().startswith('```'):
            print('  SUSPICIOUS fence:', f_line)
    print(f'Total ``` count: {text.count("```")}')
