import sys
sys.stdout.reconfigure(encoding='utf-8')
from voice_engine import classify_intent, strip_wake_word, contains_wake_word, _tts_mode

tests = [
    'Hey Blitz show me financials',
    'Jarvis open habits tracker',
    'what is our runway',
    'stop listening',
    'show dashboard',
    'log my workout today',
    'hey blitz board prep',
]
print('=== Voice Engine Intent Tests ===')
for t in tests:
    cleaned = strip_wake_word(t)
    intent = classify_intent(cleaned)
    wake = contains_wake_word(t)
    tag = 'WAKE' if wake else '    '
    print(f'  [{tag}] "{t}" -> {intent} | cleaned: "{cleaned}"')

print()
print(f'TTS engine: {_tts_mode} (edge = Microsoft Neural)')
print('Wake words: hey blitz, blitz, jarvis, hey jarvis, computer')
print('Voice endpoints: POST /api/voice/command, POST /api/voice/tts, GET /api/voice/status, WS /ws/voice')
