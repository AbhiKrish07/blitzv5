import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# The broken tasks line - find exact string and replace
idx = content.find('tl.innerHTML=t.length?t.slice(0,6)')
end_idx = content.find("join(''):'<div style=\"color:var(--muted);font-size:11px\">No pending tasks", idx)
end_idx = content.find("};", end_idx) + 2  # find the closing

# Get the broken chunk
broken = content[idx:end_idx]
print('BROKEN FOUND:', repr(broken[:80]))

# Build the correct replacement
fixed = """var tItems='';
  for(var _ti=0;_ti<Math.min(t.length,6);_ti++){
    var tk=t[_ti];
    var pri={urgent:'🔴',high:'🟠',medium:'🟡',low:'🟢'}[tk.priority]||'⚪';
    var due=tk.due?' <span style="color:var(--muted);font-family:var(--mono);font-size:9px">'+tk.due+'</span>':'';
    tItems+='<div style="padding:4px 0;border-bottom:1px solid var(--faint);font-size:11px">'+pri+' '+esc(tk.title)+due+'</div>';
  }
  tl.innerHTML=t.length?tItems:'<div style="color:var(--muted);font-size:11px">No pending tasks ✅</div>';"""

# We need to find the EXACT end of the broken line
# The broken inline ends at the closing quote + semicolon
old_search_start = content.find("tl.innerHTML=t.length?t.slice(0,6).map(tk=>`")
old_search_end = content.find("No pending tasks", old_search_start)
old_search_end = content.find("`;", old_search_end) + 2

old_chunk = content[old_search_start:old_search_end]
print('Replacing chunk of length:', len(old_chunk))

content = content[:old_search_start] + fixed + content[old_search_end:]

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('Tasks HTML fix applied.')
