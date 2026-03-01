import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add Chart.js to <head> before </head>
if 'chart.umd.min.js' not in content[:3000]:
    content = content.replace(
        '</head>',
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>\n</head>'
    )
    print('Added Chart.js to head')

# 2. Remove the duplicate dynamic Chart.js injection (lines 904-907)
content = content.replace(
    '    // Chart.js for graphs\n    const script = document.createElement(\'script\');\n    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js";\n    document.head.appendChild(script);\n\n',
    ''
)
print('Removed dynamic chart.js injection')

# 3. Add Habits nav item if missing
if 'nav-habits' not in content:
    content = content.replace(
        '<div class="sb-item" onclick="showView(\'market\')" id="nav-market"><span class="sb-icon">📈</span>Market Intel</div>',
        '<div class="sb-item" onclick="showView(\'market\')" id="nav-market"><span class="sb-icon">📈</span>Market Intel</div>\n      <div class="sb-item" onclick="showView(\'habits\')" id="nav-habits"><span class="sb-icon">🧘</span>Habits</div>'
    )
    print('Added Habits nav item')
else:
    print('Habits nav already exists')

# 4. Add auto-seed call in init
if 'seed' not in content[-3000:]:
    content = content.replace(
        '(async function init(){\n  load_digest();\n  loadRightPanel();\n})();',
        '(async function init(){\n  // Auto-seed agency data on first load\n  api(\'/api/ceo/seed\', \'POST\').then(d => { if(d && d.seeded && d.seeded.length > 0) console.log(\'[BLITZ] Seeded:\', d.seeded); });\n  load_digest();\n  loadRightPanel();\n})();'
    )
    print('Added auto-seed to init')
else:
    print('seed already in init area')

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('All fixes applied. File written.')
