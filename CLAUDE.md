# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## What this project does

Voice note pipeline: Easy Voice Recorder (Android) → Google Drive → `~/voice-inbox/` (via rclone) → `pipeline.py` → faster-whisper transcription (CUDA) → Claude formats as structured Obsidian note(s) → NAS-mounted Obsidian vaults.

n8n (192.168.1.155:5678) handles daily note creation (06:00) and archiving notes older than 7 days (06:05) separately from this pipeline.

## Commands

```bash
# Run tests (uses real Claude API — costs money)
source .env && export ANTHROPIC_API_KEY
.venv/bin/python tests/test_pipeline.py

# Run the pipeline manually (watches ~/voice-inbox/)
source .venv/bin/activate
ANTHROPIC_API_KEY=$(grep ANTHROPIC .env | cut -d= -f2) python pipeline.py

# Service management
sudo systemctl status voice-pipeline.service
sudo journalctl -u voice-pipeline.service -f
```

## Architecture

**`config.py`** — all paths and model constants. Edit here to change vault locations, Whisper model, or Claude model.

**`prompts.py`** — the entire Claude interaction. `SYSTEM` defines note structure, vault routing rules, and output schema. `user_prompt()` builds the per-request message with transcript, date, existing daily notes (for `daily_append` detection), and existing note titles (for backlink suggestions).

**`pipeline.py`** — watchdog loop over `~/voice-inbox/`. On a new audio file:
1. Transcribe with faster-whisper
2. Call Claude → returns a JSON array of note objects (never a bare object)
3. `add_cross_links()` injects sibling links when a recording splits across vaults
4. Write each note to the appropriate vault; `daily_append` type appends to an existing daily note instead of creating
5. Touch a `.done` marker, then move audio to `/mnt/nas/voice-archive/`

The `.done` marker prevents reprocessing if the service restarts before NAS archiving completes.

## Note schema (Claude output)

Each note object: `vault` (`personal`|`work`), `type` (`daily`|`daily_append`|`topic`), `folder`, `filename`, `title`, `tags[]`, `content`.

- **daily** — new daily note with full template (Most Important Thing, Urgent, Maintenance, Gratitude, Worth Noting, Dataview block)
- **daily_append** — content appended to existing daily note with a timestamp separator
- **topic** — standalone note with Summary / Key Points / Action Items / Related sections
- Mixed recordings produce **two note objects** — one per vault, content split cleanly, cross-linked via `add_cross_links()`

## Key paths

| Path | Purpose |
|------|---------|
| `~/voice-inbox/` | rclone drops audio here; pipeline watches this |
| `/mnt/nas/Obsidian/Personal` | Personal vault |
| `/mnt/nas/Obsidian/Work` | Work vault |
| `/mnt/nas/voice-archive/` | Processed audio moved here |
| `~/.cache/huggingface/` | Whisper large-v3 model cache (~3 GB) |

## Test suite

`tests/test_pipeline.py` is an acceptance suite — it calls the real Claude API for most cases and `add_cross_links()` directly for unit tests. Run it to verify routing, vault splitting, backlinks, Dataview block inclusion, and `daily_append` behavior. It exits non-zero on any failure.
