import asyncio, sys, os
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    from voice_engine import synthesize_speech, format_jarvis_response, _tts_mode
    print(f'TTS mode: {_tts_mode}')
    
    # Test synthesis
    test_text = "Good morning, boss. All systems are online. Your MRR is at eighty-eight thousand dollars, up eleven percent month over month. You have two overdue commitments requiring attention."
    formatted = format_jarvis_response(test_text, add_prefix=True)
    print(f'Formatted for TTS: {formatted}')
    
    audio = await synthesize_speech(formatted)
    if audio:
        with open('test_tts_output.mp3', 'wb') as f:
            f.write(audio)
        print(f'TTS SUCCESS: {len(audio)} bytes written to test_tts_output.mp3')
    else:
        print('TTS returned None (may need internet connection for edge-tts)')

asyncio.run(main())
