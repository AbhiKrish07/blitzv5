import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the right panel alerts - they're rendering raw HTML because of template literal issues
# The tasks list also shows raw HTML. Find and fix loadRightPanel

# Fix the tasks list - it uses a template literal with complex content
# Find the broken tl.innerHTML line
old_tasks = """  tl.innerHTML=t.length?t.slice(0,6).map(tk=>`< div style = "padding:4px 0;border-bottom:1px solid var(--faint);font-size:11px" >{ urgent: '🔴', high: '🟠', medium: '🟡', low: '🟢' } [tk.priority] || '⚪' } ${ esc(tk.title) }${ tk.due ? ' <span style="color:var(--muted);font-family:var(--mono);font-size:9px">' + tk.due + '</span>' : '' }</div > `).join(''):'<div style="color:var(--muted);font-size:11px">No pending tasks ✅</div>';"""

new_tasks = """  var tItems = '';
  for(var i=0;i<Math.min(t.length,6);i++){
    var tk=t[i];
    var pri={urgent:'🔴',high:'🟠',medium:'🟡',low:'🟢'}[tk.priority]||'⚪';
    tItems+='<div style="padding:4px 0;border-bottom:1px solid var(--faint);font-size:11px">'+pri+' '+esc(tk.title)+(tk.due?'<span style="color:var(--muted);font-family:var(--mono);font-size:9px"> '+tk.due+'</span>':'')+'</div>';
  }
  tl.innerHTML = t.length ? tItems : '<div style="color:var(--muted);font-size:11px">No pending tasks ✅</div>';"""

# Fix alerts
old_alerts1 = """  if(fin?.alert)alertsHtml+=`< div class="alert-card" ><div class="alert-title">🔴 Finance</div><div class="alert-text">${esc(fin.alert)}</div></div > `;
  if(fin?.warning)alertsHtml+=`< div class="alert-card warn" ><div class="alert-title">⚠️ Finance</div><div class="alert-text">${esc(fin.warning)}</div></div > `;"""
new_alerts1 = """  if(fin && fin.alert) alertsHtml += '<div class="alert-card"><div class="alert-title">🔴 Finance</div><div class="alert-text">'+esc(fin.alert)+'</div></div>';
  if(fin && fin.warning) alertsHtml += '<div class="alert-card warn"><div class="alert-title">⚠️ Finance</div><div class="alert-text">'+esc(fin.warning)+'</div></div>';"""

old_alerts2 = """  overdue.forEach(p=>{alertsHtml+=`< div class="alert-card" ><div class="alert-title">🔴 Overdue</div><div class="alert-text">${esc(p.what)}</div></div > `;});"""
new_alerts2 = """  overdue.forEach(function(p){alertsHtml+='<div class="alert-card"><div class="alert-title">🔴 Overdue</div><div class="alert-text">'+esc(p.what)+'</div></div>';});"""

# Fix quick command response
old_qcmd = """    mc.innerHTML=`< div class="card" style = "border-color:rgba(129,140,248,.2)" ><div class="card-header"><span class="card-title">💬 Jarvis Response</span></div><div class="digest-text">${esc(d.response)}</div></div >`;"""
new_qcmd = """    mc.innerHTML = '<div class="card" style="border-color:rgba(129,140,248,.2)"><div class="card-header"><span class="card-title">💬 Jarvis Response</span></div><div class="digest-text">'+esc(d.response)+'</div></div>';"""

fixes = [
    (old_tasks, new_tasks, 'tasks list'),
    (old_alerts1, new_alerts1, 'alerts fin'),
    (old_alerts2, new_alerts2, 'alerts overdue'),
    (old_qcmd, new_qcmd, 'quick cmd response'),
]

for old, new, name in fixes:
    if old in content:
        content = content.replace(old, new)
        print(f'Fixed: {name}')
    else:
        print(f'NOT FOUND: {name}')

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
