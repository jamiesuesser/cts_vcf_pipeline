#!/bin/bash
export TMPDIR="${TMPDIR:-/localscratch/$SLURM_JOB_ID}"
export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$TMPDIR $JAVA_TOOL_OPTIONS"
exec bash "$@"
