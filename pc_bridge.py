"""
B.L.I.T.Z. Local PC Bridge — runs silently on Windows.
Connects to the Render server via WebSocket and executes system commands locally.
Run this on your Windows PC: python pc_bridge.py
"""
import asyncio, json, os, subprocess, sys, time
import websockets
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.getenv("BLITZ_SERVER_URL", "wss://your-render-url.onrender.com/ws/bridge")
AUTH_TOKEN = os.getenv("BLITZ_PASSPHRASE", "blitz-jarvis-2025")
RECONNECT_DELAY = 5  # seconds


# ── Command executors ─────────────────────────────────────────────────────────
def open_app(name: str) -> dict:
    app_map = {
        "vscode": "code",
        "vs code": "code",
        "notepad": "notepad",
        "calculator": "calc",
        "chrome": "chrome",
        "firefox": "firefox",
        "discord": "discord",
        "spotify": "spotify",
        "explorer": "explorer",
        "terminal": "wt",  # Windows Terminal
        "cmd": "cmd",
        "paint": "mspaint",
    }
    key = name.lower().strip()
    cmd = app_map.get(key, key)
    try:
        subprocess.Popen(cmd, shell=True)
        return {"status": "ok", "message": f"Opened {name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def set_volume(level: int = None, mute: bool = False) -> dict:
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        import ctypes
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))
        if mute:
            volume.SetMute(1, None)
            return {"status": "ok", "message": "Muted"}
        if level is not None:
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return {"status": "ok", "message": f"Volume set to {level}%"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def set_brightness(level: int) -> dict:
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        return {"status": "ok", "message": f"Brightness set to {level}%"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_system_info() -> dict:
    try:
        import psutil
        return {
            "cpu": psutil.cpu_percent(interval=1),
            "ram": round(psutil.virtual_memory().percent, 1),
            "battery": psutil.sensors_battery()._asdict() if psutil.sensors_battery() else None,
            "disk": round(psutil.disk_usage('/').percent, 1)
        }
    except Exception as e:
        return {"error": str(e)}


def take_screenshot() -> dict:
    try:
        import pyautogui
        import base64, io
        img = pyautogui.screenshot()
        # Resize to save bandwidth
        img = img.resize((1280, 720))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"status": "ok", "image_b64": b64}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def control_spotify(action: str) -> dict:
    """Control Spotify via keyboard shortcuts."""
    try:
        import pyautogui
        action_map = {
            "play":     lambda: pyautogui.hotkey("ctrl", "alt", "space"),
            "pause":    lambda: pyautogui.hotkey("ctrl", "alt", "space"),
            "next":     lambda: pyautogui.hotkey("ctrl", "alt", "right"),
            "previous": lambda: pyautogui.hotkey("ctrl", "alt", "left"),
        }
        fn = action_map.get(action)
        if fn:
            fn()
            return {"status": "ok", "action": action}
        return {"status": "error", "message": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def execute_command(cmd_data: dict) -> dict:
    """Route incoming command to appropriate executor.
    
    Server sends: {"type": "command", "cmd_type": "open_app", "payload": {...}, "request_id": "..."}
    We read cmd_type (not type, which is always "command").
    """
    # cmd_type is what the server sends as the actual command identifier
    cmd_type = cmd_data.get("cmd_type") or cmd_data.get("type", "")
    payload  = cmd_data.get("payload", {})
    
    if cmd_type == "open_app":
        return open_app(payload.get("name", ""))
    elif cmd_type == "set_volume":
        return set_volume(payload.get("level"), payload.get("mute", False))
    elif cmd_type == "set_brightness":
        return set_brightness(payload.get("level", 50))
    elif cmd_type == "system_info":
        return get_system_info()
    elif cmd_type == "screenshot":
        return take_screenshot()
    elif cmd_type == "spotify":
        return control_spotify(payload.get("action", "play"))
    elif cmd_type == "run_cmd":
        # Run arbitrary shell command (careful!)
        safe_cmds = ["dir", "whoami", "echo", "date", "time"]
        raw = payload.get("command", "")
        if any(raw.strip().lower().startswith(s) for s in safe_cmds):
            result = subprocess.run(raw, shell=True, capture_output=True, text=True, timeout=5)
            return {"status": "ok", "stdout": result.stdout, "stderr": result.stderr}
        return {"status": "error", "message": "Command not in safe list"}
    else:
        return {"status": "error", "message": f"Unknown command type: {cmd_type}"}


# ── WebSocket bridge ──────────────────────────────────────────────────────────
async def run_bridge():
    print(f"[BRIDGE] Connecting to {SERVER_URL}")
    while True:
        try:
            async with websockets.connect(
                SERVER_URL,
                extra_headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
                ping_interval=30,
                ping_timeout=10
            ) as ws:
                print("[BRIDGE] Connected to server ✓")
                
                # Identify as PC bridge
                await ws.send(json.dumps({"type": "bridge_hello", "platform": "windows"}))
                
                async for message in ws:
                    try:
                        data = json.loads(message)
                        
                        if data.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                            continue
                        
                        if data.get("type") == "command":
                            print(f"[BRIDGE] Executing: {data.get('cmd_type', '?')}")
                            result = execute_command(data)
                            result["request_id"] = data.get("request_id")
                            await ws.send(json.dumps({"type": "command_result", "data": result}))
                    
                    except json.JSONDecodeError:
                        print(f"[BRIDGE] Invalid JSON received")
                    except Exception as e:
                        print(f"[BRIDGE] Command error: {e}")
        
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"[BRIDGE] Disconnected: {e}. Reconnecting in {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)
        except Exception as e:
            print(f"[BRIDGE] Unexpected error: {e}. Reconnecting...")
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    print("=" * 50)
    print("  B.L.I.T.Z. PC Bridge v1.0")
    print("  This script runs silently in the background.")
    print("  Keep this window open.")
    print("=" * 50)
    
    # Install dependencies if missing
    try:
        import websockets
    except ImportError:
        print("[BRIDGE] Installing websockets...")
        subprocess.run([sys.executable, "-m", "pip", "install", "websockets"], check=True)
        import websockets
    
    asyncio.run(run_bridge())
