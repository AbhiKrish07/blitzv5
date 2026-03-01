import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the tasks line character position precisely
start = content.find("tl.innerHTML=t.length?t.slice")
print("start:", start)
# Print a longer chunk around it
print(repr(content[start:start+600]))
