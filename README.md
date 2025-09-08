# Server Idle Watchdog (auto-shutdown VM when empty)

Shuts down the GCP VM if the Valheim server has **zero players** for a configurable time window. Everything (units, script, config) lives in this Git repo. Systemd loads the units via absolute paths.

## Requirements
- Ubuntu/Debian VM with systemd.
- Docker running a Valheim server (e.g., `loesche/valheim`).
- Host exposes UDP **2456–2458** to the container so the VM can query A2S on **2457**.
- Python 3 + `a2s` library.

## Repo layout
```
/opt/systemd-units/server-scripts/
├─ server-idle.env
├─ server-idle-shutdown.py
├─ server-idle-shutdown.service
└─ server-idle-shutdown.timer
```

> Adjust the base path if you prefer. All unit references must stay **absolute**.

## Install

1) Clone to the target path:
```bash
sudo install -d -m 755 /opt/systemd-units
cd /opt/systemd-units
sudo git clone https://github.com/gsmcclellan/google-game-server-scripts.git server-scripts
cd server-scripts
```

2) Install dependencies:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip
sudo python3 -m pip install 'a2s>=1.3,<2.0'
```

3) Make the script executable:
```bash
sudo chmod +x /opt/systemd-units/server-scripts/server-idle-shutdown.py
```

4) Verify unit syntax:
```bash
sudo systemd-analyze verify   /opt/systemd-units/server-scripts/server-idle-shutdown.service   /opt/systemd-units/server-scripts/server-idle-shutdown.timer
```

5) Enable units (systemd creates symlinks under `/etc/systemd/system`):
```bash
sudo systemctl enable /opt/systemd-units/server-scripts/server-idle-shutdown.service
sudo systemctl enable --now /opt/systemd-units/server-scripts/server-idle-shutdown.timer
```

6) Confirm:
```bash
systemctl status server-idle-shutdown.timer
systemctl list-timers | grep server-idle-shutdown || true
```

## Configuration

Edit the env file in-repo:

`/opt/systemd-units/server-scripts/server-idle.env`
```ini
# VM queries this address/port (127.0.0.1 if ports are published to host)
SERVER_HOST=127.0.0.1
# Steam A2S query port (usually game port+1; Valheim default => 2457)
SERVER_QUERY_PORT=2457

# Minutes with zero players before shutdown
IDLE_MINUTES=60
# Prevent immediate shutdown if IDLE_MINUTES too low, not recommended to set both these values very low or the server will 
# shutdown quickly & you may not be able to change settings before it shuts down.
BOOT_GRACE_MINUTES=3

# A2S robustness
A2S_TIMEOUT_SEC=2
A2S_RETRIES=3
A2S_RETRY_DELAY_SEC=3

# State file (keep outside Git)
STATE_FILE=/var/lib/server-idle/last_active.txt

# Container to stop gracefully before poweroff
CONTAINER_NAME=dst-server
```

Changes to `server-idle.env` take effect on the **next timer run**; no reload required.


## Operations

- Change idle window:
  ```bash
  sudoedit /opt/systemd-units/server-scripts/server-idle.env   # set IDLE_MINUTES
  # takes effect next timer tick
  ```

- Run the Python Script
```bash
python3 /opt/systemd-units/server-scripts/server-idle-shutdown.py
```

- Run a check now:
  ```bash
  sudo systemctl start server-idle-shutdown.service
  ```

- Logs:
  ```bash
  journalctl -u server-idle-shutdown.service -n 100 -f

  # live tail of the unit’s output
  journalctl -fu server-idle-shutdown.service

  # last run’s logs
  journalctl -u server-idle-shutdown.service -n 50 --no-pager

  # quick status with recent lines
  systemctl status server-idle-shutdown.service
  ```

- See next run time:
  ```bash
  systemctl list-timers | grep server-idle-shutdown
  ```

- Update units or script (after Git pull/edit):
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl restart server-idle-shutdown.timer
  ```

- Disable/uninstall:
  ```bash
  sudo systemctl disable --now server-idle-shutdown.timer
  sudo systemctl disable server-idle-shutdown.service
  # keep or remove the repo directory
  ```

## Testing

- Fast test: set `IDLE_MINUTES=5`, wait with **no players** connected, confirm VM powers off.
- Manual simulate “activity”: 
  ```bash
  echo $(date +%s) | sudo tee /var/lib/server-idle/last_active.txt
  ```
  then run the service once; it should *not* shut down.

## Troubleshooting

- Timer won’t start:
  ```bash
  systemctl status server-idle-shutdown.timer
  journalctl -u server-idle-shutdown.timer -b
  sudo systemd-analyze verify /opt/systemd-units/server-scripts/server-idle-shutdown.{service,timer}
  ```

- Service errors:
  ```bash
  systemctl status server-idle-shutdown.service
  journalctl -u server-idle-shutdown.service -b -n 200 --no-pager
  ```

- Verify the A2S query works (quick Python one-liner):
  ```bash
  python3 - <<'PY'
  import a2s; print(a2s.info(("127.0.0.1",2457)))
  PY
  ```
  If this times out, ensure the query port is reachable on the host (publish 2457/udp from the container).

- Check permissions related to calling python file from service
```
S=/opt/systemd-units/server-scripts/server-idle-shutdown.py
# 1) correct shebang
sudo sed -i '1s|^.*$|#!/usr/bin/env python3|' "$S"
# 2) no CRLF/BOM
sudo sed -i 's/\r$//' "$S"; sudo sed -i '1s/^\xEF\xBB\xBF//' "$S"
# 3) executable bit and ownership
sudo chmod 755 "$S"; sudo chown root:root "$S"
# 4) /opt is not mounted noexec
findmnt -no OPTIONS /opt | grep -q noexec && echo "noexec on /opt -> use python ExecStart instead"
```

## Notes

- `EnvironmentFile` must use an **absolute** path.
- The state file directory is created automatically (`/var/lib/server-idle`).
- Root is used to allow `docker stop` and `shutdown` without extra capability setup. If you run non-root, you must grant `CAP_SYS_BOOT` and Docker access.
