#!/bin/bash
# On-target depth for one BAM (one SLURM array task). Submitted by run_pipeline.py.
# Args: BAM_LIST OUT_DIR TARGET_BED MOSDEPTH_BIN MIN_MAPQ MIN_DEPTH
#SBATCH -t 4:00:00
#SBATCH -c 4
#SBATCH --mem=16G
set -euo pipefail

LIST=$1; OUTD=$2; BED=$3; MOSDEPTH=$4; MAPQ=$5; MIND=$6

bam=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$LIST")
id=$(basename "$bam" .bam)

"$MOSDEPTH" -t 4 -n --fast-mode -Q "$MAPQ" --by "$BED" --thresholds "$MIND" \
    "$OUTD/$id" "$bam"
