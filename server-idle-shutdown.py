#!/usr/bin/env python3
import os, time, pathlib, subprocess, socket, sys
from datetime import datetime, timezone
import a2s

def env(name, default=None, cast=str):
    v = os.environ.get(name, default)
    if v is None: return None
    return cast(v)

HOST              = env("SERVER_HOST", "127.0.0.1")
PORT              = env("SERVER_QUERY_PORT", "2457", int)
IDLE_MINUTES      = env("IDLE_MINUTES", "60", int)
A2S_TIMEOUT       = env("A2S_TIMEOUT_SEC", "2", float)
A2S_RETRIES       = env("A2S_RETRIES", "3", int)
A2S_RETRY_DELAY   = env("A2S_RETRY_DELAY_SEC", "3", float)
STATE_FILE        = env("STATE_FILE", "/var/lib/server-idle/last_active.txt")
CONTAINER_NAME    = env("CONTAINER_NAME", "game-server")

STATE_DIR = str(pathlib.Path(STATE_FILE).parent)

def now_ts() -> int:
    return int(time.time())

def read_last_active() -> int:
    try:
        return int(pathlib.Path(STATE_FILE).read_text().strip())
    except Exception:
        return now_ts()  # initialize on first run

def write_last_active(ts: int):
    pathlib.Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
    pathlib.Path(STATE_FILE).write_text(str(int(ts)))

def query_player_count(host: str, port: int) -> tuple[bool,int]:
    """Return (reachable, player_count)."""
    addr = (host, int(port))
    a2s.defaults.timeout = A2S_TIMEOUT
    # Try a few times to ride out packet loss
    for _ in range(A2S_RETRIES):
        try:
            info = a2s.info(addr)
            # Prefer info.player_count (cheap); players() would be heavier
            return True, int(getattr(info, "player_count", 0))
        except Exception:
            time.sleep(A2S_RETRY_DELAY)
    return False, 0

def docker_stop(name: str):
    try:
        subprocess.run(
            ["docker", "stop", "-t", "180", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
    except Exception:
        pass

def log(msg: str):
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] {msg}", flush=True)
    try:
        subprocess.run(["logger", msg], check=False)
    except Exception:
        pass

def main():
    last_active = read_last_active()
    reachable, count = query_player_count(HOST, PORT)
    now = now_ts()

    if reachable:
        log(f"A2S ok; players={count}")
        if count > 0:
            write_last_active(now)
            log("Players online -> refreshed last_active")
            return
    else:
        log("A2S unreachable; not refreshing last_active (will not immediately shut down)")

    idle_sec = now - last_active
    threshold_sec = IDLE_MINUTES * 60
    log(f"Idle_for={idle_sec}s threshold={threshold_sec}s")

    if idle_sec >= threshold_sec:
        log(f"Idle >= threshold -> stopping container '{CONTAINER_NAME}' then powering off.")
        docker_stop(CONTAINER_NAME)
        # Power off the VM (GCE will see a clean guest shutdown)
        subprocess.run(["/sbin/shutdown", "-h", "now"])
    else:
        log("Below threshold -> do nothing")

if __name__ == "__main__":
    main()