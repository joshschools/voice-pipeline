#!/usr/bin/env python3
import json
import logging
import re
import shutil
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Literal

import anthropic
from anthropic import APIConnectionError, APIStatusError
from faster_whisper import WhisperModel
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
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

# Cache of existing topic-note titles. NAS rglob is expensive; rebuild at most every TTL.
_TITLE_CACHE: dict = {"ts": 0.0, "titles": []}
_TITLE_CACHE_TTL_SEC = 60
_TITLE_LIMIT = 75
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class Note(BaseModel):
    vault: Literal["personal", "work"]
    type: Literal["daily", "daily_append", "topic"]
    folder: str
    filename: str
    title: str
    tags: list[str] = Field(default_factory=list)
    content: str


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
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    text = " ".join(s.text.strip() for s in segments)
    log.info(f"Transcribed {info.duration:.0f}s of audio → {len(text)} chars")
    return text


def get_existing_notes() -> list[str]:
    """Return titles of non-daily, non-archive notes for backlink context.

    Cached for `_TITLE_CACHE_TTL_SEC` and capped at `_TITLE_LIMIT` newest entries
    (by date prefix) to bound NAS I/O and prompt-token cost.
    """
    now = time.time()
    if _TITLE_CACHE["titles"] and now - _TITLE_CACHE["ts"] < _TITLE_CACHE_TTL_SEC:
        return _TITLE_CACHE["titles"]

    skip = {"Daily", "Archive", "Readwise"}
    titles: list[str] = []
    for vault in (config.PERSONAL_VAULT, config.WORK_VAULT):
        if not vault.exists():
            continue
        for path in vault.rglob("*.md"):
            if not skip.intersection(path.parts):
                titles.append(path.stem)

    if len(titles) > _TITLE_LIMIT:
        dated = sorted(t for t in titles if _DATE_RE.match(t))
        undated = sorted(t for t in titles if not _DATE_RE.match(t))
        keep = max(0, _TITLE_LIMIT - len(undated))
        titles = sorted(undated + dated[-keep:]) if keep else sorted(undated)[:_TITLE_LIMIT]
    else:
        titles.sort()

    _TITLE_CACHE["ts"] = now
    _TITLE_CACHE["titles"] = titles
    return titles


def _invalidate_title_cache() -> None:
    _TITLE_CACHE["ts"] = 0.0


def _stem(filename: str) -> str:
    return filename[:-3] if filename.endswith(".md") else filename


def add_cross_links(notes: list[dict]) -> list[dict]:
    """Inject sibling note links into each note's Related section.

    Obsidian resolves [[wikilinks]] by filename stem, so a sibling that shares
    this note's filename (e.g. two daily notes both named 2026-05-19.md, one per
    vault) would link back to the note itself. Skip those, and dedupe by stem so
    an ambiguous target is never linked twice.
    """
    if len(notes) <= 1:
        return notes
    for i, note in enumerate(notes):
        own_stem = _stem(note["filename"])
        seen: set[str] = set()
        links: list[str] = []
        for j, n in enumerate(notes):
            if j == i:
                continue
            stem = _stem(n["filename"])
            if stem == own_stem or stem in seen:
                continue
            seen.add(stem)
            links.append(f"- [[{stem}|{n['title']}]]")
        content = note["content"].replace("- [[link to related note if one exists, otherwise omit]]", "").strip()
        if not links:
            note["content"] = content
            continue
        siblings = "\n".join(links)
        if "## Related" in content:
            content += f"\n{siblings}"
        else:
            content += f"\n\n## Related\n{siblings}"
        note["content"] = content
    return notes


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((APIStatusError, APIConnectionError)),
    reraise=True,
)
def _call_claude(client: anthropic.Anthropic, user_content: str):
    return client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_TOKENS,
        system=[{
            "type": "text",
            "text": prompts.SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_content}],
    )


def _parse_claude_json(raw: str) -> list[dict]:
    """Parse Claude's response, tolerating fences and stray prose around the JSON array."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def format_note(client: anthropic.Anthropic, transcript: str, recorded_at: datetime) -> list[dict]:
    date_str = recorded_at.strftime("%Y-%m-%d")

    personal_daily_path = config.PERSONAL_VAULT / "Daily" / f"{date_str}.md"
    work_daily_path = config.WORK_VAULT / "Daily" / f"{date_str}.md"
    personal_daily = personal_daily_path.read_text() if personal_daily_path.exists() else None
    work_daily = work_daily_path.read_text() if work_daily_path.exists() else None
    existing_notes = get_existing_notes()

    user_content = prompts.user_prompt(
        transcript, date_str, personal_daily, work_daily, existing_notes
    )
    response = _call_claude(client, user_content)

    raw = response.content[0].text
    try:
        parsed = _parse_claude_json(raw)
    except json.JSONDecodeError:
        log.error(f"Claude returned invalid JSON:\n{raw}")
        raise

    items = parsed if isinstance(parsed, list) else [parsed]
    notes: list[dict] = []
    for item in items:
        try:
            notes.append(Note(**item).model_dump())
        except ValidationError as e:
            log.error(f"Claude returned invalid note shape: {e}\nNote: {item}")
            raise
    return add_cross_links(notes)


def _safe_note_path(note: dict) -> Path:
    """Resolve the destination path and verify it stays inside the chosen vault."""
    vault_root = config.PERSONAL_VAULT if note["vault"] == "personal" else config.WORK_VAULT
    filename = note["filename"]
    folder = note["folder"]

    if not filename or "/" in filename or "\\" in filename or filename.startswith(".") or ".." in filename:
        raise ValueError(f"Unsafe filename: {filename!r}")
    if Path(folder).is_absolute():
        raise ValueError(f"Folder must be vault-relative: {folder!r}")
    if any(p in ("..", "") for p in Path(folder).parts):
        raise ValueError(f"Unsafe folder: {folder!r}")

    note_path = (vault_root / folder / filename).resolve()
    if not note_path.is_relative_to(vault_root.resolve()):
        raise ValueError(f"Note path escapes vault: {note_path}")
    return note_path


def write_note(note: dict) -> Path:
    note_path = _safe_note_path(note)
    note_path.parent.mkdir(parents=True, exist_ok=True)

    if note["type"] == "daily_append" and note_path.exists():
        timestamp = datetime.now().strftime("%H:%M")
        note_path.write_text(
            note_path.read_text().rstrip()
            + f"\n\n---\n*Addendum — {timestamp}*\n\n"
            + note["content"].strip()
            + "\n"
        )
        log.info(f"Appended to {note_path}")
        _invalidate_title_cache()
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
    _invalidate_title_cache()
    return note_path


def _archive_audio(audio_path: Path, done_marker: Path) -> bool:
    try:
        config.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.ARCHIVE_DIR / audio_path.name
        shutil.move(str(audio_path), dest)
        done_marker.unlink(missing_ok=True)
        log.info(f"Audio archived → {dest}")
        return True
    except Exception:
        log.warning(f"Could not archive audio (NAS offline?): {audio_path.name} — leaving in inbox")
        return False


def _quarantine(audio_path: Path, error: BaseException) -> None:
    """Move a failing file out of the watched inbox so it stops looping on restart."""
    failed_dir = config.INBOX_DIR / "failed"
    try:
        failed_dir.mkdir(parents=True, exist_ok=True)
        (failed_dir / f"{audio_path.name}.error").write_text(
            f"{datetime.now().isoformat()}\n{error!r}\n\n{traceback.format_exc()}\n"
        )
        shutil.move(str(audio_path), failed_dir / audio_path.name)
        log.error(f"Quarantined → {failed_dir / audio_path.name}")
    except Exception:
        log.exception(f"Could not quarantine {audio_path.name}")


def _sweep_pending_archives() -> None:
    """Retry archiving any audio whose note was already written (.done marker) on a prior run."""
    if not config.INBOX_DIR.exists():
        return
    for done in config.INBOX_DIR.glob("*.done"):
        audio = done.with_name(done.name[:-len(".done")])
        if not audio.exists():
            log.info(f"Removing orphan marker (audio gone): {done.name}")
            done.unlink(missing_ok=True)
            continue
        log.info(f"Resuming pending archive: {audio.name}")
        _archive_audio(audio, done)


def _wait_for_stable_size(path: Path, max_wait_s: int = 15) -> bool:
    """Wait until the file's size has been steady for one tick. Returns False if file vanishes."""
    prev = -1
    for _ in range(max_wait_s):
        if not path.exists():
            return False
        size = path.stat().st_size
        if size > 0 and size == prev:
            return True
        prev = size
        time.sleep(1)
    return path.exists()


def process(audio_path: Path, whisper: WhisperModel, claude: anthropic.Anthropic):
    log.info(f"─── Processing: {audio_path.name} ───")
    recorded_at = datetime.fromtimestamp(audio_path.stat().st_mtime)

    transcript = transcribe(whisper, audio_path)
    notes = format_note(claude, transcript, recorded_at)
    for note in notes:
        log.info(f"Routed → {note['vault']}/{note['folder']}/{note['filename']} (type={note['type']})")

    note_path = write_note(notes[0])
    for note in notes[1:]:
        write_note(note)

    done_marker = audio_path.with_name(audio_path.name + ".done")
    done_marker.touch()
    _archive_audio(audio_path, done_marker)
    log.info(f"─── Done: {note_path.name} ───")


class AudioHandler(FileSystemEventHandler):
    def __init__(self, whisper: WhisperModel, claude: anthropic.Anthropic):
        self.whisper = whisper
        self.claude = claude

    def _handle(self, path: Path):
        if path.suffix.lower() not in config.AUDIO_EXTENSIONS:
            return
        if path.with_name(path.name + ".done").exists():
            return
        if not _wait_for_stable_size(path):
            return
        try:
            process(path, self.whisper, self.claude)
        except Exception as e:
            log.exception(f"Failed to process {path.name}")
            _quarantine(path, e)

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

    _sweep_pending_archives()

    # Process anything already in the inbox (e.g. dropped while service was down)
    for f in config.INBOX_DIR.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        if f.with_name(f.name + ".done").exists():
            continue
        try:
            process(f, whisper, claude)
        except Exception as e:
            log.exception(f"Failed to process existing file {f.name}")
            _quarantine(f, e)

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
