#!/bin/bash
set -euo pipefail

DATE=$(date +%Y-%m-%d)
DOW=$(date +%A)

PERSONAL_DIR="/mnt/nas/Obsidian/Personal/Daily"
WORK_DIR="/mnt/nas/Obsidian/Work/Daily"

mkdir -p "$PERSONAL_DIR" "$WORK_DIR"

# Personal daily note — every day
PERSONAL_NOTE="$PERSONAL_DIR/${DATE}.md"
if [[ ! -f "$PERSONAL_NOTE" ]]; then
    cat > "$PERSONAL_NOTE" <<EOF
---
title: Daily — ${DATE}
date: ${DATE}
type: daily
tags:
  - daily
  - reflection
---

# Daily — ${DATE}

## Most Important Thing


## Urgent


## Maintenance


## Gratitude


## Worth Noting
EOF
    echo "Created personal daily note: ${DATE}"
else
    echo "Personal note already exists: ${DATE}"
fi

# Work daily note — weekdays only
if [[ "$DOW" != "Saturday" && "$DOW" != "Sunday" ]]; then
    WORK_NOTE="$WORK_DIR/${DATE}.md"
    if [[ ! -f "$WORK_NOTE" ]]; then
        cat > "$WORK_NOTE" <<EOF
---
title: Work — ${DATE}
date: ${DATE}
type: daily
tags:
  - daily
  - work
---

# Work — ${DATE}

## Most Important Thing


## Urgent


## Maintenance


## Worth Noting
EOF
        echo "Created work daily note: ${DATE}"
    else
        echo "Work note already exists: ${DATE}"
    fi
fi
