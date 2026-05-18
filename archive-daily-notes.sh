#!/bin/bash
# Move daily notes older than 7 days to Archive/Daily/YYYY-MM/ in each vault.
# Grouped by month so the archive stays navigable.

set -euo pipefail

KEEP_DAYS=7
VAULTS=(
    "/mnt/nas/Obsidian/Personal"
    "/mnt/nas/Obsidian/Work"
)

for VAULT in "${VAULTS[@]}"; do
    DAILY_DIR="$VAULT/Daily"
    [[ -d "$DAILY_DIR" ]] || continue

    while IFS= read -r -d '' note; do
        filename=$(basename "$note")
        note_date="${filename%.md}"

        # Skip files that aren't dated YYYY-MM-DD
        [[ "$note_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue

        age=$(( ( $(date +%s) - $(date -d "$note_date" +%s) ) / 86400 ))
        (( age <= KEEP_DAYS )) && continue

        month="${note_date:0:7}"   # e.g. 2026-05
        dest_dir="$VAULT/Archive/Daily/$month"
        mkdir -p "$dest_dir"

        mv "$note" "$dest_dir/$filename"
        echo "Archived: $filename → $(basename "$VAULT")/Archive/Daily/$month/"
    done < <(find "$DAILY_DIR" -maxdepth 1 -name "*.md" -print0)
done
