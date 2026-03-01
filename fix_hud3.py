import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add financial chart canvas + render call after the KPI rows in load_financials
OLD_FIN_END = """    <div id="fin-narrative" style="margin-top:8px"></div>`;
    }"""

NEW_FIN_END = """    <div class="card" style="padding:20px;margin-top:12px">
      <div class="card-title" style="margin-bottom:10px">📈 6-Month Financial Trend</div>
      <canvas id="fin-chart-hud" height="140"></canvas>
    </div>
    <div id="fin-narrative" style="margin-top:8px"></div>`;
      // Render financial chart
      var _finSnaps = data.all_snapshots || [];
      if (_finSnaps.length > 1 && typeof Chart !== 'undefined') {
        setTimeout(function() {
          var ctx = document.getElementById('fin-chart-hud');
          if (!ctx) return;
          if (window._finChartHud) window._finChartHud.destroy();
          var labels = _finSnaps.map(function(s) { return s.period; });
          window._finChartHud = new Chart(ctx, {
            type: 'line',
            data: {
              labels: labels,
              datasets: [
                { label: 'MRR ($)', data: _finSnaps.map(function(s){return s.mrr||0;}), borderColor:'#a78bfa', backgroundColor:'#a78bfa22', fill:true, tension:0.4, borderWidth:2, pointRadius:4 },
                { label: 'Cash ($)', data: _finSnaps.map(function(s){return s.cash||0;}), borderColor:'#4ade80', backgroundColor:'#4ade8022', fill:true, tension:0.4, borderWidth:2, pointRadius:4, yAxisID:'y1' }
              ]
            },
            options: {
              responsive:true,
              interaction:{mode:'index',intersect:false},
              plugins:{ legend:{ position:'bottom', labels:{color:'rgba(255,255,255,.6)',font:{size:11}} } },
              scales:{
                y:{ position:'left', ticks:{color:'rgba(255,255,255,.4)', callback:function(v){return '$'+(v/1000).toFixed(0)+'k';}}, grid:{color:'rgba(255,255,255,.05)'} },
                y1:{ position:'right', ticks:{color:'rgba(255,255,255,.4)', callback:function(v){return '$'+(v/1000).toFixed(0)+'k';}}, grid:{display:false} },
                x:{ ticks:{color:'rgba(255,255,255,.4)'}, grid:{color:'rgba(255,255,255,.05)'} }
              }
            }
          });
        }, 150);
      }
    }"""

if OLD_FIN_END in content:
    content = content.replace(OLD_FIN_END, NEW_FIN_END)
    print('Added financial chart')
else:
    print('ERROR: could not find fin end marker')
    print(repr(content[content.find('fin-narrative'):content.find('fin-narrative')+100]))

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')
