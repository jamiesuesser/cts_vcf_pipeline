#!/bin/bash
# Downloads snpArcher into vcf_pipeline/snpArcher and applies the CTS edits
# (see SNParcher_changes.md section 1) on git branch "targeted-calling".
# Run once:  bash /projects/cts/jamie/vcf_pipeline/scripts/setup_snparcher.sh
# Already have snpArcher/? Update it instead:  bash .../scripts/update_snparcher.sh
set -euo pipefail

PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PIPE/snpArcher"
COMMIT="8a73e5b"   # snpArcher version these edits were tested on

if [ -e "$DEST" ]; then
    echo "ERROR: $DEST already exists. Remove it first if you want a fresh copy."
    exit 1
fi

git clone https://github.com/harvardinformatics/snpArcher.git "$DEST"
cd "$DEST"
git checkout -q -b targeted-calling "$COMMIT"

python3 "$PIPE/scripts/patch_snparcher.py" "$DEST"

git -c user.name="CTS pipeline" -c user.email="cts@localhost" commit -qam \
    "CTS: restrict HaplotypeCaller and interval chunks to target BED"
echo
git log --oneline -2
echo
git diff --stat HEAD~1
echo
echo "snpArcher ready at $DEST (branch targeted-calling)."
