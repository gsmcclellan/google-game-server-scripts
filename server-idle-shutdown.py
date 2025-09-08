#!/usr/bin/env python3
import os, time, pathlib, subprocess, socket, sys
from datetime import datetime, timezone
from pathlib import Path
import a2s

def env(name, default=None, cast=str):
    v = os.environ.get(name, default)
    if v is None: return None
    return cast(v)

HOST              = env("SERVER_HOST", "127.0.0.1")
PORTS = [int(p) for p in str(env("VALHEIM_QUERY_PORT", "27016")).split(",")]
IDLE_MINUTES      = env("IDLE_MINUTES", "60", int)
BOOT_GRACE_MINUTES = env("BOOT_GRACE_MINUTES","3", int)
A2S_TIMEOUT       = env("A2S_TIMEOUT_SEC", "2", float)
A2S_RETRIES       = env("A2S_RETRIES", "3", int)
A2S_RETRY_DELAY   = env("A2S_RETRY_DELAY_SEC", "3", float)
STATE_FILE        = env("STATE_FILE", "/var/lib/server-idle/last_activez.txt")
CONTAINER_NAME    = env("CONTAINER_NAME", "game-server")

STATE_DIR = str(pathlib.Path(STATE_FILE).parent)

def now_ts() -> int:
    return int(time.time())

def read_last_active():
    p = Path(STATE_FILE)
    if p.exists():
        try:
            return int(p.read_text().strip())
        except Exception:
            pass  # fall through to reset if file is corrupt

    # First run or unreadable file: initialize and persist once
    ts = now_ts()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(ts))
    return ts

def write_last_active(ts: int):
    pathlib.Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
    pathlib.Path(STATE_FILE).write_text(str(int(ts)))

def query_total_players(host: str, ports):
    total = 0
    any_ok = False
    for p in ports:
        ok, count = query_player_count(host, p)
        if ok:
            any_ok = True
            total += count
    return any_ok, total

def query_player_count(host: str, port: int):
    addr = (host, int(port))
    for _ in range(A2S_RETRIES):
        try:
            info = a2s.info(addr, timeout=A2S_TIMEOUT)  # timeout passed here
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

def boot_time_ts() -> int:
    try:
        with open("/proc/uptime","r") as f:
            up = float(f.read().split()[0])
        return int(time.time() - up)
    except Exception:
        return int(time.time())

def main():
    now = now_ts()
    boot_ts = boot_time_ts()

    last_active = read_last_active()

    # If the saved timestamp is from before this boot, peg it to boot time.
    if last_active < boot_ts:
        write_last_active(boot_ts)
        last_active = boot_ts
        log("Reset last_active to boot time")

    reachable, count = query_total_players(HOST, PORTS)

    if reachable:
        log(f"A2S ok; players={count}")
        if count > 0:
            write_last_active(now)
            log("Players online -> refreshed last_active")
            return
    else:
        log("A2S unreachable; not refreshing last_active (will not immediately shut down)")

    grace_until = boot_ts + BOOT_GRACE_MINUTES*60
    idle_sec = now - last_active
    threshold_sec = IDLE_MINUTES * 60
    log(f"Idle_for={idle_sec}s threshold={threshold_sec}s")

    if now < grace_until:
        log(f"In boot grace window ({grace_until - now}s left) -> do nothing")
        return

    if idle_sec >= threshold_sec:
        log(f"Idle >= threshold -> stopping container '{CONTAINER_NAME}' then powering off.")
        docker_stop(CONTAINER_NAME)
        # Power off the VM (GCE will see a clean guest shutdown)
        subprocess.run(["/sbin/shutdown", "-h", "now"])
    else:
        log("Below threshold -> do nothing")

if __name__ == "__main__":
    main()