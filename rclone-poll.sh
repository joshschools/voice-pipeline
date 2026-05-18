#!/bin/bash
# Move new recordings from Google Drive into the local voice inbox.
# Uses "move" so files are removed from Drive after download — prevents reprocessing.
# The pipeline archives processed audio to NAS.

DRIVE_FOLDER="Easy Voice Recorder"
INBOX="/home/jschools/voice-inbox"

rclone move "gdrive:${DRIVE_FOLDER}" "${INBOX}" \
    --include "*.m4a" \
    --include "*.mp3" \
    --include "*.wav" \
    --include "*.ogg" \
    --include "*.opus" \
    --include "*.flac" \
    --include "*.aac" \
    --transfers 2 \
    --log-level INFO
