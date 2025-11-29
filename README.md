````markdown
# Ajbot 🧠🔧  
Discord bot for Proxmox control, Minecraft server management, and music playback via Lavalink — all running in Docker.

![Repo stars](https://img.shields.io/github/stars/Beniaminexe/ajbot?style=flat-square)
![Issues](https://img.shields.io/github/issues/Beniaminexe/ajbot?style=flat-square)
![Last commit](https://img.shields.io/github/last-commit/Beniaminexe/ajbot?style=flat-square)
![Docker](https://img.shields.io/badge/docker-compose-blue?style=flat-square)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Configuration](#configuration)
  - [.env](#env)
  - [Lavalink (`application.yml`)](#lavalink-applicationyml)
- [Running with Docker Compose](#running-with-docker-compose)
- [Discord Commands](#discord-commands)
  - [`!mcup`](#mcup)
  - [`!mcdown`](#mcdown)
- [Auto-deploy (Git pull + restart)](#auto-deploy-git-pull--restart)
  - [`deploy.sh` script](#deploysh-script)
  - [Cron job example](#cron-job-example)
  - [Systemd unit (`ajbot.service`)](#systemd-unit-ajbotservice)
- [Proxmox Layout](#proxmox-layout)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [License](#license)

---

## Overview

Ajbot is a self-hosted Discord bot designed to live in a Proxmox homelab. It can:

- Talk to the **Proxmox API** to start/stop VMs and containers.
- Manage a dedicated **Minecraft server container** with simple commands.
- Play music via **Lavalink** and **Wavelink**, running alongside the bot in Docker.

The bot itself runs inside a container (e.g. on Proxmox CT `1000`), and controls other VMs/CTs via the Proxmox API (e.g. a Minecraft container on `CT 302`).

---

## Features

- ✅ Discord bot using `discord.py`
- ✅ Proxmox API integration (via API token)
- ✅ Start/stop Proxmox containers and VMs
- ✅ Dedicated commands for a Minecraft server container
- ✅ Music playback using Lavalink + Wavelink
- ✅ Docker + `docker-compose` deployment
- ✅ Optional auto-deploy on Git push (cron + `deploy.sh`)
- ✅ Optional systemd unit to start the stack on boot

---

## Architecture

High-level components:

- **Ajbot (Discord bot)**  
  - Python application (`bot.py`)  
  - Uses environment variables for Discord + Proxmox config  
  - Runs inside a Docker container built from this repo.

- **Lavalink**  
  - Runs as a separate service in Docker.  
  - Configured via `application.yml`.  
  - Used by the bot for audio playback.

- **Proxmox**  
  - Ajbot talks to the Proxmox API over HTTPS.  
  - Proxmox API token is stored in `.env`.  
  - Ajbot can start/stop VMs/LXCs by ID.

---

## Requirements

- A running **Proxmox** node
- A **Discord bot** and its token
- A **Proxmox API token** with permission to start/stop your VMs/containers
- On the host where Ajbot runs (e.g. Proxmox LXC CT `1000`):
  - `git`
  - `docker`
  - `docker-compose` or `docker compose` plugin

You also need a dedicated container/VM in Proxmox for your Minecraft server (e.g. CT `302`).

---

## Configuration

### `.env`

The bot reads its settings from a `.env` file in the repo root.

Create a `.env` file (do **not** commit it to git):

```env
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN

# Proxmox API
PVE_HOST=https://YOUR-PROXMOX-HOST:8006
PVE_USER=root@pam
PVE_TOKEN_ID=YOUR-PVE-TOKEN-ID       # e.g. ajbot@pve!bot
PVE_TOKEN_SECRET=YOUR-PVE-TOKEN-SECRET
PVE_NODE=YOUR-PROXMOX-NODE-NAME      # e.g. pve

# (Optional) Lavalink-related environment variables if used by the code
# LAVALINK_HOST=lavalink
# LAVALINK_PORT=2333
# LAVALINK_PASSWORD=youshallnotpass
````

> Keep `.env` out of version control. Add it to `.gitignore` if needed.

### Lavalink (`application.yml`)

Lavalink uses `application.yml` in the repo. The exact config depends on your setup, but typical options are:

* Server port (e.g. `2333`)
* Password (e.g. `youshallnotpass`)
* Audio settings / filters

Ensure that:

* The **Lavalink container** is reachable at the host/port the bot expects.
* The **password** in `application.yml` matches what the bot uses.

The Docker Compose file in this repo is expected to wire `application.yml` into the Lavalink container.

---

## Running with Docker Compose

Once `.env` and `application.yml` are configured:

```bash
git clone https://github.com/Beniaminexe/ajbot.git
cd ajbot

# Start in detached mode
docker compose up -d
# or, if using classic docker-compose:
# docker-compose up -d
```

To stop:

```bash
docker compose down
# or: docker-compose down
```

Check logs:

```bash
docker compose logs -f
# or: docker-compose logs -f
```

You should see the bot logging into Discord and connecting to Lavalink.

---

## Discord Commands

Only the key Proxmox/Minecraft commands are described here. Music commands depend on the implementation in `bot.py`, but typically include `!play`, `!stop`, etc.

### `!mcup`

Starts the Minecraft server **LXC container** on Proxmox (e.g. CT `302`):

```text
!mcup
```

Internally, this calls the Proxmox API:

* Node: `PVE_NODE` (from `.env`)
* Container ID: `302` (hardcoded in the bot as `MC_CTID = 302`)
* API endpoint: `nodes/{PVE_NODE}/lxc/302/status/start`

The bot replies in Discord with status messages indicating whether the start request was sent successfully.

### `!mcdown`

Stops (shuts down) the Minecraft server container:

```text
!mcdown
```

Internally, this calls:

* `nodes/{PVE_NODE}/lxc/302/status/shutdown`

If the container refuses a graceful shutdown, the bot can be adjusted to use `.status.stop.post()` instead for a hard stop (see `bot.py`).

> **Note:** The actual command prefix (e.g. `!`) and the full command set is defined in `bot.py`.

---

## Auto-deploy (Git pull + restart)

This repository supports a simple "auto-update on git push" flow, typically used on the Proxmox LXC where Ajbot runs (e.g. CT `1000`).

### `deploy.sh` script

A typical `deploy.sh` in the repo root looks like:

```bash
#!/usr/bin/env bash
set -e

REPO_DIR="/root/discord-pve-bot"
BRANCH="main"

cd "$REPO_DIR"

git fetch origin "$BRANCH"

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date)] New commit detected, deploying..."

    git pull origin "$BRANCH"

    # Adjust to your docker-compose path and style
    docker compose pull || true
    docker compose up -d --build
    # or:
    # /usr/bin/docker-compose pull || true
    # /usr/bin/docker-compose up -d --build

    echo "[$(date)] Deploy complete."
else
    echo "[$(date)] No changes, nothing to do."
fi
```

This script:

1. Checks if the local repo is behind `origin/main`.
2. Pulls new commits if needed.
3. Restarts/rebuilds the Docker stack.

### Cron job example

To have the bot auto-update every 5 minutes, add a cron job (on the Ajbot host, as root):

```bash
crontab -e
```

Example entry:

```cron
*/5 * * * * /root/discord-pve-bot/deploy.sh >> /var/log/ajbot-deploy.log 2>&1
```

This will:

* Check GitHub every 5 minutes
* Pull new code if available
* Rebuild/restart the Docker containers

### Systemd unit (`ajbot.service`)

To auto-start Ajbot on boot, create:

`/etc/systemd/system/ajbot.service`:

```ini
[Unit]
Description=Ajbot Discord Bot (docker compose)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/root/discord-pve-bot
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Then:

```bash
systemctl daemon-reload
systemctl enable ajbot
systemctl start ajbot
systemctl status ajbot
```

Adjust `/usr/bin/docker` and the working directory path if your setup is different.

---

## Proxmox Layout

A typical layout for this bot is:

* **CT 1000** – `ajbot`

  * Runs Docker + Ajbot containers (bot + Lavalink)
  * Has the git clone of this repo
  * Runs cron + systemd for auto-update and startup

* **CT 302** – `mc-server`

  * Runs the Minecraft server
  * Controlled by Ajbot via:

    * `!mcup` → start container
    * `!mcdown` → shutdown container

Other VMs/containers can be controlled similarly by adding more commands or using existing generic helpers in `bot.py`.

---

## Troubleshooting

* **Bot not online in Discord**

  * Check `DISCORD_TOKEN` in `.env`
  * Check Docker logs: `docker compose logs -f`

* **Cannot control Proxmox**

  * Verify `PVE_HOST`, `PVE_USER`, `PVE_TOKEN_ID`, `PVE_TOKEN_SECRET`, `PVE_NODE`
  * Ensure the Proxmox API token has correct permissions (e.g. `VM.PowerMgmt`)

* **Minecraft server not starting**

  * Confirm the container ID is actually `302` in Proxmox
  * Check Proxmox tasks / logs for container start errors

* **Music not working**

  * Confirm Lavalink is running (container is healthy)
  * Confirm the bot can reach Lavalink (host/port/password match)

---

## Security Notes

* Do **not** commit `.env` to Git. It contains secrets.
* Treat your Proxmox API token like a password.
* Restrict the Proxmox token permissions to only what the bot needs (power operations on specific VMs/CTs).
* Run Ajbot in an isolated Proxmox container/VM with limited access, not on your main node directly.

---

## License

No explicit license is defined yet.
If you fork or reuse this code, treat it as private unless a `LICENSE` file is added to this repository.

---

