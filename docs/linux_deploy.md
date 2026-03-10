# Linux Deployment

## 1. Copy Project

From Windows PowerShell:

```powershell
scp -r c:\code\agent-meeting-room root@10.168.21.10:/root/
```

## 2. Install Python Environment

On the Linux host:

```bash
cd /root/agent-meeting-room
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Start Service

```bash
cd /root/agent-meeting-room
source .venv/bin/activate
AMR_HOST=0.0.0.0 AMR_PORT=8000 python main.py
```

## 4. Open in Browser

Use:

- http://10.168.21.10:8000

## 5. Background Run Example

```bash
cd /root/agent-meeting-room
source .venv/bin/activate
nohup env AMR_HOST=0.0.0.0 AMR_PORT=8000 python main.py > agent-room.log 2>&1 &
```

## 6. Notes

- SQLite data file is created at data/agent_meeting_room.db.
- First startup seeds the room, default roles, and LLM profiles.
- If you plan to expose the service outside a trusted network, add authentication before doing so.