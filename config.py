from pathlib import Path

# --- Folders ---
INBOX_DIR   = Path("/home/jschools/voice-inbox")    # Syncthing drops audio here
ARCHIVE_DIR = Path("/mnt/nas/voice-archive")  # processed audio goes here (NAS)

PERSONAL_VAULT = Path("/home/jschools/Documents/Personal")
WORK_VAULT     = Path("/home/jschools/Documents/Work")

# --- Whisper ---
WHISPER_MODEL        = "large-v3"
WHISPER_DEVICE       = "cuda"
WHISPER_COMPUTE_TYPE = "float16"

# --- Claude ---
CLAUDE_MODEL  = "claude-sonnet-4-6"
CLAUDE_TOKENS = 2048

# --- Audio ---
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".aac"}
