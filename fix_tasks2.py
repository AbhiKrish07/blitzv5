import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# The broken chunk ends right before "\n  // Update promise badge"
end_marker = "\n  // Update promise badge"
start = content.find("tl.innerHTML=t.length?t.slice")
end = content.find(end_marker, start)
print(f"Replacing chars {start} to {end}, len={end-start}")

fixed = """var tItems='';
  for(var _ti=0;_ti<Math.min(t.length,6);_ti++){
    var tk=t[_ti];
    var pri={urgent:'\ud83d\udd34',high:'\ud83d\udfe0',medium:'\ud83d\udfe1',low:'\ud83d\udfe2'}[tk.priority]||'\u26aa';
    var due=tk.due?' <span style="color:var(--muted);font-family:var(--mono);font-size:9px">'+tk.due+'</span>':'';
    tItems+='<div style="padding:4px 0;border-bottom:1px solid var(--faint);font-size:11px">'+pri+' '+esc(tk.title)+due+'</div>';
  }
  tl.innerHTML=t.length?tItems:'<div style="color:var(--muted);font-size:11px">No pending tasks \u2705</div>';"""

content = content[:start] + fixed + content[end:]

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Tasks fix applied successfully.')
