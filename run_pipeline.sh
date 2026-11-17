#!/bin/bash
# CTS VCF pipeline launcher. Run from /projects/cts/jamie:
#   bash vcf_pipeline/run_pipeline.sh                 full run (submits a small SLURM "controller" job)
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

# Long runs (full run, --depth-only) run in a small SLURM job (the "controller"),
# NOT on the login node: ARC limits CPU use on login nodes, and Snakemake
# managing ~1000 jobs used ~7.5 CPUs there (ARC asked us to move it, 2026-11-11).
# The controller job submits and tracks all the pipeline's other jobs.
# Set controller_on_login_node: true in the settings to use the old screen session.
case " $* " in *" --dry-run "*|*" --prepare-only "*|*" --unlock "*) LONG=0 ;; *) LONG=1 ;; esac
if [ "$LONG" = 1 ] && [ -z "${STY:-}" ] && [ -z "${CTS_CONTROLLER:-}" ] \
   && [ "$(getval controller_on_login_node)" != "true" ]; then
    JOB="ctl_${RUN}"
    if squeue -u "$USER" -h -n "$JOB" -o %i | grep -q .; then
        echo "A controller job named $JOB is already queued/running: squeue -u $USER -n $JOB"
        exit 1
    fi
    mkdir -p "$ROOT/$RUN"
    LOG="$ROOT/$RUN/pipeline_console.log"
    ARGS=""
    if [ $# -gt 0 ]; then ARGS=$(printf ' %q' "$@"); fi
    JID=$(sbatch --parsable -J "$JOB" -A "$(getval slurm_account)" -p "$(getval slurm_partition)" \
        -c 2 --mem=8G -t 7-00:00:00 -o "$LOG" --open-mode=append \
        --export=ALL,CTS_CONTROLLER=1 \
        --wrap "bash $(printf %q "$PIPE/run_pipeline.sh")$ARGS")
    echo "Submitted controller job $JID ($JOB): 2 cores, 8 GB, up to 7 days."
    echo "  follow log:   tail -f $LOG"
    echo "  stop the run: scancel $JID   (then scancel -u \$USER for jobs it started)"
    exit 0
fi
if [ "$LONG" = 1 ] && [ -z "${STY:-}" ] && [ -z "${CTS_CONTROLLER:-}" ]; then
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
export PATH="$PIPE/bin:$PATH"   # srun wrapper (see bin/srun)
# Keep the controller light: no multi-threaded math libraries
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONUNBUFFERED=1

set +e
python "$PIPE/scripts/run_pipeline.py" "$@"
rc=$?
if [ -n "${STY:-}" ] && [ "$LONG" = 1 ]; then
    echo; echo "Pipeline finished (exit code $rc). Press Enter to close this screen session."
    read -r _
fi
exit $rc
