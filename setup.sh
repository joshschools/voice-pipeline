#!/bin/bash
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Voice Pipeline Setup ==="
echo ""

# System dependencies
echo "[1/4] Installing system packages..."
sudo dnf install -y python3-pip python3-venv rclone

# Python venv
echo "[2/4] Creating Python virtual environment..."
python3 -m venv "$PIPELINE_DIR/.venv"
source "$PIPELINE_DIR/.venv/bin/activate"
pip install --upgrade pip --quiet
pip install -r "$PIPELINE_DIR/requirements.txt"

# Download Whisper model (pulls ~3GB to ~/.cache/huggingface on first run)
echo "[3/4] Downloading Whisper large-v3 model (first run only, ~3 GB)..."
python3 -c "
from faster_whisper import WhisperModel
print('  Downloading...')
WhisperModel('large-v3', device='cuda', compute_type='float16')
print('  Model ready.')
"

# Env file for API key
if [[ ! -f "$PIPELINE_DIR/.env" ]]; then
    echo "[4/4] Creating .env file..."
    cat > "$PIPELINE_DIR/.env" <<'EOF'
ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
EOF
    echo "  Edit $PIPELINE_DIR/.env and paste your API key."
else
    echo "[4/4] .env already exists, skipping."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Get an API key at console.anthropic.com → API Keys"
echo "  2. Paste it into: $PIPELINE_DIR/.env"
echo "  3. Configure rclone Google Drive remote:"
echo "     rclone config"
echo "     Name the remote 'gdrive', choose Google Drive, follow OAuth prompts."
echo "  4. Install the systemd units:"
echo "     sudo cp $PIPELINE_DIR/voice-pipeline.service /etc/systemd/system/"
echo "     sudo cp $PIPELINE_DIR/rclone-poll.service /etc/systemd/system/"
echo "     sudo cp $PIPELINE_DIR/rclone-poll.timer /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now voice-pipeline.service rclone-poll.timer"
echo "  5. Daily note creation and archiving run via n8n (192.168.1.155:5678)."
echo "     Import n8n-morning-notes.json and n8n-archive-daily-notes.json"
echo "     and activate both workflows."
echo ""
echo "Test the pipeline manually:"
echo "  source $PIPELINE_DIR/.venv/bin/activate"
echo "  ANTHROPIC_API_KEY=\$(grep ANTHROPIC $PIPELINE_DIR/.env | cut -d= -f2) \\"
echo "    python $PIPELINE_DIR/pipeline.py"
