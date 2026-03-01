import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

end_marker = "\n  // Update promise badge"
start = content.find("tl.innerHTML=t.length?t.slice")
end = content.find(end_marker, start)
print(f"Replacing chars {start} to {end}, len={end-start}")

fixed = (
    "var tItems='';\n"
    "  for(var _ti=0;_ti<Math.min(t.length,6);_ti++){\n"
    "    var tk=t[_ti];\n"
    "    var pri={urgent:'\\U0001f534',high:'\\U0001f7e0',medium:'\\U0001f7e1',low:'\\U0001f7e2'}[tk.priority]||'\\u26aa';\n"
    "    var due=tk.due?' <span style=\"color:var(--muted);font-family:var(--mono);font-size:9px\">'+tk.due+'</span>':'';\n"
    "    tItems+='<div style=\"padding:4px 0;border-bottom:1px solid var(--faint);font-size:11px\">'+pri+' '+esc(tk.title)+due+'</div>';\n"
    "  }\n"
    "  tl.innerHTML=t.length?tItems:'<div style=\"color:var(--muted);font-size:11px\">No pending tasks</div>';"
)

# Use actual unicode chars, not escape sequences
fixed = fixed.replace("'\\U0001f534'", "'\U0001f534'")
fixed = fixed.replace("'\\U0001f7e0'", "'\U0001f7e0'")
fixed = fixed.replace("'\\U0001f7e1'", "'\U0001f7e1'")
fixed = fixed.replace("'\\U0001f7e2'", "'\U0001f7e2'")
fixed = fixed.replace("'\\u26aa'", "'\u26aa'")

content = content[:start] + fixed + content[end:]

# Remove any surrogate chars that may exist
content = content.encode('utf-8', errors='replace').decode('utf-8')

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Tasks fix applied.')
