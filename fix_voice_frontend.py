import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('jarvis_hud.html', 'r', encoding='utf-8') as f:
    content = f.read()

OLD = '''  _voiceRec.onresult = async function(event) {
    const transcript = event.results[0][0].transcript;
    document.getElementById('quick-cmd').value = transcript;
    
    // Command Routing
    const lower = transcript.toLowerCase();
    if (lower.includes('dashboard') || lower.includes('home')) { showView('digest'); }
    else if (lower.includes('money') || lower.includes('financial') || lower.includes('revenue')) { showView('financials'); }
    else if (lower.includes('okr') || lower.includes('goal')) { showView('okrs'); }
    else if (lower.includes('promise') || lower.includes('commitment')) { showView('promises'); }
    else if (lower.includes('compet') || lower.includes('intel') || lower.includes('market')) { showView(lower.includes('market') ? 'market' : 'competitors'); }
    else if (lower.includes('team') || lower.includes('org')) { showView('org'); }
    else if (lower.includes('people') || lower.includes('contact')) { showView('contacts'); }
    else if (lower.includes('habit') || lower.includes('development')) { showView('habits'); }
    else if (lower.includes('workflow') || lower.includes('automation')) { showView('workflows'); }
    else if (lower.includes('bio') || lower.includes('body')) { showView('biometrics'); }
    else {
      // General question - ask Jarvis
      sendQuickCmd();
    }
  };

  _voiceRec.onerror = function(e) { console.error('Voice error:', e); stopVoiceOrb(); };
  _voiceRec.onend = function() { stopVoiceOrb(); };
  _voiceRec.start();
}

function stopVoiceOrb() {
  _isListening = false;
  document.getElementById('voice-orb').classList.remove('listening');
}'''

NEW = '''  _voiceRec.onresult = async function(event) {
    const transcript = event.results[0][0].transcript;
    document.getElementById('quick-cmd').value = transcript;
    showVoiceToast('Heard: "' + transcript + '"');
    try {
      const r = await fetch('/api/voice/command', { method:'POST', headers:H,
        body: JSON.stringify({ text: transcript, include_audio: true }) });
      const d = await r.json();
      if (d.nav_target) showView(d.nav_target);
      if (d.action === 'board_prep') genBoardBriefing();
      if (d.action === 'refresh') loadDigest();
      if (d.action === 'seed') { await api('/api/ceo/seed','POST'); load_habits(); }
      if (d.response) {
        document.getElementById('quick-cmd').placeholder = d.response;
        setTimeout(function(){ document.getElementById('quick-cmd').placeholder='Ask Jarvis anything...';},5000);
      }
      if (d.audio_b64) {
        playBase64Audio(d.audio_b64, d.audio_mime||'audio/mpeg');
      } else if (d.response && 'speechSynthesis' in window) {
        speakBrowserTTS(d.response);
      }
      if (!d.nav_target && d.response && !d.action) {
        var mc = document.getElementById('main-content');
        mc.innerHTML = '<div class="card" style="border-color:rgba(129,140,248,.2)">' +
          '<div class="card-header"><span class="card-title">Jarvis</span>' +
          '<span class="card-badge">'+(d.intent||'voice')+'</span></div>' +
          '<div class="digest-text" style="margin-top:8px">'+esc(d.response)+'</div></div>';
      }
    } catch(err) {
      console.error('[Voice] error:', err);
      var lower = transcript.toLowerCase();
      if (lower.includes('dashboard')||lower.includes('home')) showView('digest');
      else if (lower.includes('financial')||lower.includes('revenue')) showView('financials');
      else if (lower.includes('habit')||lower.includes('development')) showView('habits');
      else if (lower.includes('okr')||lower.includes('goal')) showView('okrs');
      else { document.getElementById('quick-cmd').value=transcript; sendQuickCmd(); }
    }
  };
  _voiceRec.onerror = function(e) { if(e.error!=='aborted') showVoiceToast('Mic error: '+e.error); stopVoiceOrb(); };
  _voiceRec.onend = function() { stopVoiceOrb(); };
  _voiceRec.start();
}

function stopVoiceOrb() {
  _isListening = false;
  document.getElementById('voice-orb').classList.remove('listening');
}

function playBase64Audio(b64, mime) {
  try {
    var bin=atob(b64), buf=new Uint8Array(bin.length);
    for(var i=0;i<bin.length;i++) buf[i]=bin.charCodeAt(i);
    var url=URL.createObjectURL(new Blob([buf],{type:mime}));
    var a=new Audio(url); a.onended=function(){URL.revokeObjectURL(url);};
    a.play().catch(function(e){console.warn('[TTS] blocked:',e); speakBrowserTTS('');});
  } catch(e){console.error('[TTS]',e);}
}

function speakBrowserTTS(text) {
  if(!('speechSynthesis' in window)||!text) return;
  window.speechSynthesis.cancel();
  var u=new SpeechSynthesisUtterance(text);
  var voices=window.speechSynthesis.getVoices();
  var pref=voices.find(function(v){return v.name.includes('David')||v.name.includes('Male')||v.name.includes('UK English Male');});
  if(pref) u.voice=pref;
  u.rate=0.92; u.pitch=0.85; u.volume=1;
  window.speechSynthesis.speak(u);
}

var _toastTimer=null;
function showVoiceToast(msg) {
  var t=document.getElementById('voice-toast');
  if(!t){
    t=document.createElement('div'); t.id='voice-toast';
    t.style.cssText='position:fixed;bottom:90px;right:24px;z-index:9999;background:rgba(10,12,22,.92);' +
      'border:1px solid rgba(129,140,248,.35);border-radius:10px;padding:8px 14px;' +
      'font-family:var(--mono);font-size:11px;color:var(--text);backdrop-filter:blur(12px);' +
      'max-width:260px;transition:opacity .3s;pointer-events:none;';
    document.body.appendChild(t);
  }
  t.textContent=msg; t.style.opacity='1';
  if(_toastTimer) clearTimeout(_toastTimer);
  _toastTimer=setTimeout(function(){t.style.opacity='0';},4000);
}'''

if OLD in content:
    content = content.replace(OLD, NEW)
    print('Voice pipeline replaced successfully')
else:
    print('OLD not found verbatim - trying line-by-line search')
    idx = content.find('_voiceRec.onresult')
    print('onresult at:', idx)

with open('jarvis_hud.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
