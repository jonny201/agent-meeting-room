# Agent Meeting Room

Python Web UI application for collaborative rooms that mix AI agents and real people.

## Features

- Web-based conversation workspace that runs on Windows or Linux
- Simple graphical participant creation for human and AI roles
- Graphical LLM profile management for OpenAI-compatible providers
- Persistent tasks, messages, review decisions, and long-term memory in SQLite
- AI replies enriched with task context and relevant memories

## Local Run

```bash
.venv/Scripts/python.exe main.py
```

Linux example:

```bash
python3 main.py
```

Default address:

- http://127.0.0.1:8000

## Linux Systemd Deploy

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
chmod +x scripts/install_systemd_service.sh
sudo ./scripts/install_systemd_service.sh
```

Common service commands:

```bash
systemctl status agent-meeting-room --no-pager
journalctl -u agent-meeting-room -f
```

## Main Files

- docs/design.md
- docs/linux_deploy.md
- src/agent_meeting_room/models.py
- src/agent_meeting_room/persistence.py
- src/agent_meeting_room/llm_client.py
- src/agent_meeting_room/agents.py
- src/agent_meeting_room/services.py
- src/agent_meeting_room/webapp.py
- src/agent_meeting_room/templates/dashboard.html
- src/agent_meeting_room/templates/models.html
- main.py

## Notes

- Runtime data is stored in data/agent_meeting_room.db.
- Seed LLM profiles are inserted automatically on first launch.
- Legacy single-room SQLite databases are automatically backed up with a `.legacy-<timestamp>` suffix before rebuilding the multi-room schema.
- Before sharing this repository, rotate or remove any sensitive API keys stored in local data.