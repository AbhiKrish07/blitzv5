import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the broken tasks innerHTML line
idx = content.find('tl.innerHTML')
print(f'tl.innerHTML at index: {idx}')
if idx >= 0:
    print(repr(content[idx:idx+400]))
