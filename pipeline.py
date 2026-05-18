#!/usr/bin/env python3
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

import anthropic
from faster_whisper import WhisperModel
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
import prompts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_whisper() -> WhisperModel:
    log.info(f"Loading Whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}...")
    model = WhisperModel(
        config.WHISPER_MODEL,
        device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE_TYPE,
        local_files_only=True,  # model already cached; avoids HuggingFace Hub on startup
    )
    log.info("Whisper ready.")
    return model


def transcribe(model: WhisperModel, audio_path: Path) -> str:
    segments, info = model.transcribe(str(audio_path), beam_size=5, language="en")
    text = " ".join(s.text.strip() for s in segments)
    log.info(f"Transcribed {info.duration:.0f}s of audio → {len(text)} chars")
    return text


def format_note(client: anthropic.Anthropic, transcript: str, recorded_at: datetime) -> dict:
    date_str = recorded_at.strftime("%Y-%m-%d")

    # Check if today's daily note already exists in either vault
    existing = None
    for vault in (config.PERSONAL_VAULT, config.WORK_VAULT):
        candidate = vault / "Daily" / f"{date_str}.md"
        if candidate.exists():
            existing = candidate.read_text()
            break

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_TOKENS,
        system=prompts.SYSTEM,
        messages=[{"role": "user", "content": prompts.user_prompt(transcript, date_str, existing)}],
    )

    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error(f"Claude returned invalid JSON:\n{raw}")
        raise


def write_note(note: dict) -> Path:
    vault_root = config.PERSONAL_VAULT if note["vault"] == "personal" else config.WORK_VAULT
    note_path = vault_root / note["folder"] / note["filename"]
    note_path.parent.mkdir(parents=True, exist_ok=True)

    if note["type"] == "daily_append" and note_path.exists():
        # Append timestamped addendum to existing daily note
        timestamp = datetime.now().strftime("%H:%M")
        note_path.write_text(
            note_path.read_text().rstrip()
            + f"\n\n---\n*Addendum — {timestamp}*\n\n"
            + note["content"].strip()
            + "\n"
        )
        log.info(f"Appended to {note_path}")
        return note_path

    tags_yaml = "\n".join(f"  - {t}" for t in note.get("tags", []))
    frontmatter = (
        f"---\n"
        f"title: {note['title']}\n"
        f"date: {note['filename'][:10]}\n"
        f"type: {note['type']}\n"
        f"tags:\n{tags_yaml}\n"
        f"---\n\n"
        f"# {note['title']}\n\n"
    )
    note_path.write_text(frontmatter + note["content"].strip() + "\n")
    log.info(f"Created {note_path}")
    return note_path


def process(audio_path: Path, whisper: WhisperModel, claude: anthropic.Anthropic):
    log.info(f"─── Processing: {audio_path.name} ───")
    recorded_at = datetime.fromtimestamp(audio_path.stat().st_mtime)

    transcript = transcribe(whisper, audio_path)
    note = format_note(claude, transcript, recorded_at)
    log.info(f"Routed → {note['vault']}/{note['folder']}/{note['filename']} (type={note['type']})")

    note_path = write_note(note)

    try:
        config.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.ARCHIVE_DIR / audio_path.name
        shutil.move(str(audio_path), dest)
        log.info(f"Audio archived → {dest}")
    except Exception:
        log.warning(f"Could not archive audio (NAS offline?): {audio_path.name} — leaving in inbox")
    log.info(f"─── Done: {note_path.name} ───")


class AudioHandler(FileSystemEventHandler):
    def __init__(self, whisper: WhisperModel, claude: anthropic.Anthropic):
        self.whisper = whisper
        self.claude = claude

    def _handle(self, path: Path):
        if path.suffix.lower() not in config.AUDIO_EXTENSIONS:
            return
        time.sleep(2)
        if not path.exists():
            return
        try:
            process(path, self.whisper, self.claude)
        except Exception:
            log.exception(f"Failed to process {path.name}")

    def on_created(self, event):
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event):
        # rclone downloads to a temp file then renames — dest_path is the final file
        if not event.is_directory:
            self._handle(Path(event.dest_path))


def main():
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)

    whisper = load_whisper()
    claude = anthropic.Anthropic()

    # Process anything already in the inbox (e.g. dropped while service was down)
    for f in config.INBOX_DIR.iterdir():
        if f.suffix.lower() in config.AUDIO_EXTENSIONS:
            try:
                process(f, whisper, claude)
            except Exception:
                log.exception(f"Failed to process existing file {f.name}")

    observer = Observer()
    observer.schedule(AudioHandler(whisper, claude), str(config.INBOX_DIR), recursive=False)
    observer.start()
    log.info(f"Watching {config.INBOX_DIR}  (Ctrl-C to stop)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
