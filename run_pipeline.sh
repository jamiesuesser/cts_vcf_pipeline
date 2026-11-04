#!/bin/bash
# CTS VCF pipeline launcher. Run from /projects/cts/jamie:
#   bash vcf_pipeline/run_pipeline.sh                 full run (starts its own screen session)
#   bash vcf_pipeline/run_pipeline.sh --dry-run       show what would run, run nothing
#   bash vcf_pipeline/run_pipeline.sh --prepare-only  build run folder/sample sheet/configs only
#   bash vcf_pipeline/run_pipeline.sh --depth-only    only (re)run the depth + sample summary
#   bash vcf_pipeline/run_pipeline.sh --unlock        clear a stale Snakemake lock
# Settings: vcf_pipeline/edit_me_before_running.yaml
set -euo pipefail

PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="$PIPE/edit_me_before_running.yaml"

getval() {
    grep -E "^$1:" "$SETTINGS" | head -1 | sed -E 's/^[^:]+:[[:space:]]*"?([^"#]*)"?.*/\1/' | xargs
}

RUN=$(getval run_name)
ROOT=$(getval output_root)
ENV=$(getval snparcher_conda_env)

# Long runs (full run, --depth-only) go in a detached screen session automatically
case " $* " in *" --dry-run "*|*" --prepare-only "*|*" --unlock "*) LONG=0 ;; *) LONG=1 ;; esac
if [ "$LONG" = 1 ] && [ -z "${STY:-}" ]; then
    SESSION="vcf_${RUN}"
    if screen -ls | grep -q "\.${SESSION}[[:space:]]"; then
        echo "A screen session named $SESSION already exists. Check it: screen -r $SESSION"
        exit 1
    fi
    mkdir -p "$ROOT/$RUN"
    LOG="$ROOT/$RUN/pipeline_console.log"
    screen -dmS "$SESSION" -L -Logfile "$LOG" bash "$PIPE/run_pipeline.sh" "$@"
    echo "Started in screen session: $SESSION (on $(hostname -s))"
    echo "  watch live:   screen -r $SESSION    (detach: screen -d $SESSION from another tab)"
    echo "  follow log:   tail -f $LOG"
    exit 0
fi

if ! command -v conda >/dev/null 2>&1; then
    for c in /apps/common/software/Miniconda3/*/etc/profile.d/conda.sh; do
        [ -f "$c" ] && source "$c" && break
    done
fi
command -v conda >/dev/null 2>&1 || { echo "ERROR: conda not found."; exit 1; }

eval "$(conda shell.bash hook)"
conda activate "$ENV"

set +e
python "$PIPE/scripts/run_pipeline.py" "$@"
rc=$?
if [ -n "${STY:-}" ] && [ "$LONG" = 1 ]; then
    echo; echo "Pipeline finished (exit code $rc). Press Enter to close this screen session."
    read -r _
fi
exit $rc
