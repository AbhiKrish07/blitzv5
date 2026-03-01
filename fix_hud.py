import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# The broken load_habits function has \\` (escaped backtick) instead of real backtick `
# This was caused by the multi_replace_file_content tool escaping template literals
# We need to fix these in the load_habits function area

# Strategy: find the broken section and rewrite the complete load_habits + logHabitToday functions

OLD_HABITS = '''    // ═══ HABITS VIEW ═══
    let _habitsChart = null;
    async function load_habits() {
      const mc = document.getElementById('main-content');
      const data = await api('/api/ceo/habits?months=6');
      const months = data?.months || [];
      const habits = data?.habits || {};
      const hids = Object.keys(habits);

      if (!hids.length) {
        mc.innerHTML =\\`<div class="empty">
      <div class="empty-icon">📈</div>
      <div style="font-size:16px;font-weight:700;margin-bottom:8px">Personal Development Tracker</div>
      <div style="font-size:12px;margin-bottom:16px">Track 5 daily habits and watch your accuracy grow over time.</div>
      <button class="qa-btn" style="margin:0 auto" onclick="addSampleHabits()">⚡ Load Sample Data</button>
    </div>\\`;
    return;
  }

  const colors = ['#a78bfa', '#4ade80', '#60a5fa', '#fbbf24', '#fb7185'];
  const labels = months.map(m => {
    const [y, mo] = m.split('-');
    return new Date(y, mo - 1).toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
  });

  mc.innerHTML = \\`
    <div class="card-header">
      <span class="card-title" style="font-size:16px">📈 Personal Development</span>
      <button class="qa-btn" onclick="logHabitToday()">✓ Log Today</button>
    </div>
    <div class="card" style="padding:20px;margin-bottom:16px">
      <div class="card-title" style="margin-bottom:10px">Monthly Accuracy Trend</div>
      <canvas id="jarvis-habits-chart" height="150"></canvas>
    </div>
    <div class="kpi-row" style="grid-template-columns:repeat(\\${Math.min(hids.length, 5)},1fr)">
      \\${hids.map((hid, i) => {
        const h = habits[hid];
        const latest = h.data?.[h.data.length - 1];
        const prev = h.data?.[h.data.length - 2];
        const acc = latest?.accuracy || 0;
        const delta = prev ? acc - prev.accuracy : 0;
        return \\`<div class="kpi" style="border-left:3px solid \\${colors[i % 5]}">
          <div class="kpi-label" style="text-transform:none">\\${h.icon} \\${h.name}</div>
          <div class="kpi-value">\\${acc}%</div>
          <div class="kpi-change \\${delta >= 0 ? 'up' : 'down'}">\\${delta >= 0 ? '▲' : '▼'} \\${Math.abs(delta)}%</div>
        </div>\\`;
      }).join('')}
    </div>\\`;

  setTimeout(() => {
    const ctx = document.getElementById('jarvis-habits-chart');
    if (!ctx || typeof Chart === 'undefined') return;
    if (_habitsChart) _habitsChart.destroy();
    _habitsChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: hids.map((hid, i) => ({
          label: habits[hid].icon + ' ' + habits[hid].name,
          data: (habits[hid].data || []).map(d => d.accuracy),
          borderColor: colors[i % 5],
          backgroundColor: colors[i % 5] + '22',
          fill: true,
          tension: 0.4,
          pointRadius: 4,
          pointHoverRadius: 6,
          borderWidth: 2,
        }))
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: 'bottom', labels: { color: 'rgba(255,255,255,.6)', font: { size: 11, family: 'Inter' } } },
        },
        scales: {
          y: { min: 0, max: 100, ticks: { color: 'rgba(255,255,255,.4)' }, grid: { color: 'rgba(255,255,255,.05)' } },
          x: { ticks: { color: 'rgba(255,255,255,.4)' }, grid: { color: 'rgba(255,255,255,.05)' } }
        }
      }
    });
  }, 100);
}
async function addSampleHabits(){
  await api('/api/ceo/seed', 'POST');
  load_habits();
}
async function logHabitToday(){
  const data = await api('/api/ceo/habits?months=1');
  const habits = data?.habits || {};
  const hids = Object.keys(habits);
  for(const hid of hids){
    const done = confirm(\\`Did you complete "\\${habits[hid].name}" today?\\`);
    await api('/api/ceo/habits/log', 'POST', { habit_id: hid, done });
  }
  load_habits();
}'''

NEW_HABITS = '''    // ═══ HABITS VIEW ═══
    let _habitsChart = null;
    async function load_habits() {
      const mc = document.getElementById('main-content');
      const data = await api('/api/ceo/habits?months=6');
      const months = data?.months || [];
      const habits = data?.habits || {};
      const hids = Object.keys(habits);

      if (!hids.length) {
        mc.innerHTML = `<div class="empty">
      <div class="empty-icon">📈</div>
      <div style="font-size:16px;font-weight:700;margin-bottom:8px">Personal Development Tracker</div>
      <div style="font-size:12px;margin-bottom:16px">Track 5 daily habits and watch your accuracy grow over time.</div>
      <button class="qa-btn" style="margin:0 auto" onclick="addSampleHabits()">⚡ Load Sample Data</button>
    </div>`;
        return;
      }

      const colors = ['#a78bfa', '#4ade80', '#60a5fa', '#fbbf24', '#fb7185'];
      const labels = months.map(m => {
        const [y, mo] = m.split('-');
        return new Date(y, mo - 1).toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
      });

      const kpiCards = hids.map((hid, i) => {
        const h = habits[hid];
        const latest = h.data && h.data[h.data.length - 1];
        const prev = h.data && h.data[h.data.length - 2];
        const acc = latest ? latest.accuracy : 0;
        const delta = prev ? Math.round(acc - prev.accuracy) : 0;
        return '<div class="kpi" style="border-left:3px solid '+colors[i%5]+'">' +
          '<div class="kpi-label" style="text-transform:none">'+h.icon+' '+h.name+'</div>' +
          '<div class="kpi-value">'+acc+'%</div>' +
          '<div class="kpi-change '+(delta>=0?'up':'down')+'">'+(delta>=0?'▲':'▼')+' '+Math.abs(delta)+'%</div></div>';
      }).join('');

      mc.innerHTML =
        '<div class="card-header">' +
          '<span class="card-title" style="font-size:16px">📈 Personal Development</span>' +
          '<div style="display:flex;gap:8px">' +
            '<button class="qa-btn" onclick="load_habits()">⟳ Refresh</button>' +
            '<button class="qa-btn" onclick="logHabitToday()">✓ Log Today</button>' +
          '</div>' +
        '</div>' +
        '<div class="card" style="padding:20px;margin-bottom:16px">' +
          '<div class="card-title" style="margin-bottom:10px">Monthly Accuracy Trend (6 months)</div>' +
          '<canvas id="jarvis-habits-chart" height="150"></canvas>' +
        '</div>' +
        '<div class="kpi-row" style="grid-template-columns:repeat('+Math.min(hids.length,5)+',1fr)">' +
          kpiCards +
        '</div>';

      setTimeout(function() {
        const ctx = document.getElementById('jarvis-habits-chart');
        if (!ctx || typeof Chart === 'undefined') return;
        if (_habitsChart) _habitsChart.destroy();
        _habitsChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: hids.map(function(hid, i) { return {
              label: habits[hid].icon + ' ' + habits[hid].name,
              data: (habits[hid].data || []).map(function(d) { return d.accuracy; }),
              borderColor: colors[i % 5],
              backgroundColor: colors[i % 5] + '22',
              fill: true,
              tension: 0.4,
              pointRadius: 4,
              pointHoverRadius: 6,
              borderWidth: 2,
            }; })
          },
          options: {
            responsive: true,
            plugins: {
              legend: { position: 'bottom', labels: { color: 'rgba(255,255,255,.6)', font: { size: 11, family: 'Inter' } } }
            },
            scales: {
              y: { min: 0, max: 100, ticks: { color: 'rgba(255,255,255,.4)', callback: function(v) { return v + '%'; } }, grid: { color: 'rgba(255,255,255,.05)' } },
              x: { ticks: { color: 'rgba(255,255,255,.4)' }, grid: { color: 'rgba(255,255,255,.05)' } }
            }
          }
        });
      }, 150);
    }
    async function addSampleHabits(){
      await api('/api/ceo/seed', 'POST');
      load_habits();
    }
    async function logHabitToday(){
      const data = await api('/api/ceo/habits?months=1');
      const habits = data ? data.habits : {};
      const hids = Object.keys(habits);
      for(let i=0; i<hids.length; i++){
        const hid = hids[i];
        const done = confirm('Did you complete "' + habits[hid].name + '" today?');
        await api('/api/ceo/habits/log', 'POST', { habit_id: hid, done: done });
      }
      load_habits();
    }'''

if OLD_HABITS in content:
    content = content.replace(OLD_HABITS, NEW_HABITS)
    print('Fixed habits section successfully')
else:
    print('ERROR: could not find habits section to replace')
    # Try to show what the content looks like
    idx = content.find('load_habits')
    if idx >= 0:
        print('Found load_habits at index', idx)
        print(repr(content[idx:idx+200]))

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('File written')
