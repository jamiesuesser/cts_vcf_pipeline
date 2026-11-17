#!/bin/bash
# Job status for Snakemake's cluster-generic executor: prints running | success | failed.
# Called with the SLURM job ID that sbatch --parsable returned.
id="${1%%;*}"
st=$(sacct -j "$id" -X -n -P -o State 2>/dev/null | head -1 | cut -d' ' -f1)
if [ -z "$st" ]; then
    st=$(squeue -h -j "$id" -o %T 2>/dev/null | head -1)
fi
case "$st" in
    COMPLETED) echo success ;;
    ""|PENDING|RUNNING|REQUEUED|RESIZING|SUSPENDED|CONFIGURING|COMPLETING|STAGE_OUT|SIGNALING|REQUEUE_HOLD|REQUEUE_FED)
        echo running ;;
    *) echo failed ;;   # FAILED, CANCELLED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, PREEMPTED, BOOT_FAIL, DEADLINE
esac
