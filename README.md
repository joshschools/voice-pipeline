# voice-pipeline

Voice note pipeline: record on Android → Google Drive → Linux → Obsidian.

## Flow

```
Easy Voice Recorder (Android)
  → Google Drive ("Easy Voice Recorder" folder)
  → rclone-poll.timer (60s)        → ~/voice-inbox/
  → voice-pipeline.service         → faster-whisper large-v3 (CUDA)
                                   → Claude Sonnet (structures note)
                                   → Obsidian vault (NAS)
                                   → /mnt/nas/voice-archive/
```

Daily note creation and archiving are handled by n8n workflows running in a Proxmox LXC (always-on).

## Services

| Unit | Schedule | What it does |
|------|----------|--------------|
| `voice-pipeline.service` | always-on watchdog | transcribes + routes voice notes |
| `rclone-poll.timer` | every 60s | syncs Google Drive → `~/voice-inbox` |

n8n (192.168.1.155:5678) handles:
- **Morning Notes** — 06:00 daily, creates blank daily note templates
- **Archive Daily Notes** — 06:05 daily, moves notes older than 7 days to `Archive/Daily/YYYY-MM/`

## Files

| File | Purpose |
|------|---------|
| `pipeline.py` | Main watchdog — transcribe, format, write, archive |
| `config.py` | Paths, model names, audio extensions |
| `prompts.py` | Whisper + Claude prompt templates |
| `rclone-poll.sh` | Called by rclone-poll.timer |
| `voice-pipeline.service` | systemd unit |
| `setup.sh` | First-time setup |

## Reliability

After a note is successfully written, a `.done` marker (`recording.m4a.done`) is created alongside the audio file in the inbox. If the NAS archive step fails, the marker prevents the file from being reprocessed on service restart. The marker is deleted once the audio is safely archived.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # add ANTHROPIC_API_KEY
sudo systemctl enable --now voice-pipeline.service rclone-poll.timer
```

Whisper model must be pre-cached (`large-v3` on CUDA). API key lives in `.env` (gitignored).
