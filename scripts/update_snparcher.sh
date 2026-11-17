#!/bin/bash
# Applies any CTS edits that are missing to an existing vcf_pipeline/snpArcher
# checkout (branch targeted-calling) and commits them. Safe to run more than once.
#   bash /projects/cts/jamie/vcf_pipeline/scripts/update_snparcher.sh
set -euo pipefail
PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PIPE/snpArcher"
cd "$DEST"
branch=$(git rev-parse --abbrev-ref HEAD)
[ "$branch" = "targeted-calling" ] || { echo "ERROR: $DEST is on branch $branch, expected targeted-calling"; exit 1; }
python3 "$PIPE/scripts/patch_snparcher.py" "$DEST"
if ! git diff --quiet; then
    git -c user.name="CTS pipeline" -c user.email="cts@localhost" commit -qam \
        "CTS: snpArcher edits (see vcf_pipeline/SNParcher_changes.md)"
    git log --oneline -1
    git diff --stat HEAD~1
fi
