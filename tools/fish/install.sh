#!/bin/bash
# Installs the fish helper commands (sqs, runstatus, jobstatus, checkrun) for this user.
#   bash <pipeline folder>/tools/fish/install.sh
# Copies the functions to ~/.config/fish/functions/ and writes
# ~/.config/fish/conf.d/cts_pipeline.fish with the folders read from edit_me_before_running.yaml.
# Safe to re-run (e.g. after changing output_root or moving the pipeline).
set -euo pipefail
PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SETTINGS="$PIPE/edit_me_before_running.yaml"
get() { grep -E "^$1:" "$SETTINGS" | head -1 | sed -E 's/^[^:]+:[[:space:]]*//; s/[[:space:]]+#.*$//; s/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'; }

RUNS="$(get output_root)"
ENV="$(get snparcher_conda_env)"
[ -n "$RUNS" ] || { echo "ERROR: output_root is empty in $SETTINGS"; exit 1; }

FUN="$HOME/.config/fish/functions"; CONF="$HOME/.config/fish/conf.d"
mkdir -p "$FUN" "$CONF"
for f in sqs runstatus jobstatus checkrun; do
    if [ -e "$FUN/$f.fish" ] && ! cmp -s "$FUN/$f.fish" "$PIPE/tools/fish/$f.fish"; then
        cp "$FUN/$f.fish" "$FUN/$f.fish.bak"
        echo "  (kept your old $f.fish as $f.fish.bak)"
    fi
    cp "$PIPE/tools/fish/$f.fish" "$FUN/$f.fish"
done
cat > "$CONF/cts_pipeline.fish" <<CONFEOF
# Written by $PIPE/tools/fish/install.sh - re-run it to update.
set -gx CTS_PIPELINE_DIR "$PIPE"
set -gx CTS_RUNS_DIR "$RUNS"
set -gx CTS_ENV_DIR "$ENV"
CONFEOF
echo "Installed sqs, runstatus, jobstatus, checkrun."
echo "  pipeline: $PIPE"
echo "  runs:     $RUNS"
echo "  env:      $ENV"
echo "Open a new fish shell (or run: source $CONF/cts_pipeline.fish) to use them."
command -v fish >/dev/null || echo "NOTE: fish is not on your PATH - these commands need the fish shell."
