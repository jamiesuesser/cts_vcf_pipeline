# sqs: my SLURM jobs, labeled with pipeline step and sample(s). Extra arguments go to squeue.
# Installed by tools/fish/install.sh
function sqs --description 'My SLURM jobs, labeled by step and sample'
    # Snakemake logs which samples went into each SLURM job; build jobid -> samples from all run logs
    set -l map (mktemp)
    set -l logs $CTS_RUNS_DIR/*/pipeline_console.log   # empty if none yet (no error)
    # Snakemake prints every job (its samples) first, then the SLURM submissions in the same order
    awk '
    FNR == 1 { n = 0; h = 0; on = 0 }
    { sub(/\r$/, "") }
    function flush() { if (on && !loc) { q[n++] = nm "\t" (s != "" ? s : (o != "" ? o : "-")) }; on = 0; s = ""; o = ""; nm = ""; delete seen }
    /Group job / { flush(); on = 1; loc = 0; nm = $0; sub(/.*Group job /, "", nm); sub(/ .*/, "", nm); next }
    /^rule [^ ]+:/ { flush(); on = 1; loc = 0; nm = $2; sub(/:$/, "", nm); next }
    /^localrule [^ ]+:/ { flush(); on = 1; loc = 1; next }
    on && /wildcards: / {
      if (match($0, /sample=[^,]+/)) { v = substr($0, RSTART + 7, RLENGTH - 7); if (!(v in seen)) { seen[v] = 1; s = s (s ? "," : "") v } }
      else if (s == "") { o = $0; sub(/.*wildcards: /, "", o); gsub(/ /, "", o) }
    }
    /external jobid|submitted with SLURM jobid/ {
      flush()
      id = $0; sub(/.*(external jobid .|SLURM jobid )/, "", id); sub(/[^0-9].*/, "", id)
      if (h < n) { print id "\t" q[h]; h++ }
    }' $logs /dev/null 2>/dev/null > $map
    squeue -u $USER -h -o "%i|%T|%M|%C|%m|%R|%500k" $argv | awk -F'|' -v mapf=$map '
    BEGIN { while ((getline l < mapf) > 0) { split(l, a, "\t"); r[a[1]] = a[2]; m[a[1]] = a[3] }
            fmt = "%10s %-8s %10s %4s %7s %-12s %-24s %s\n"
            printf fmt, "JOBID", "STATE", "TIME", "CPUS", "MEM", "NODE/REASON", "STEP", "SAMPLE(S)" }
    {
      c = $7; gsub(/ +$/, "", c); sub(/^rule_/, "", c); sub(/_wildcards_.*/, "", c)
      if ((c == "" || c == "(null)") && ($1 in r)) c = r[$1] "_"
      if (c == "" || c == "(null)") c = "controller/other"
      if (c ~ /^map_/) step = "map (fastp->bwa->BAM)"
      else if (c ~ /^hc_/) step = "hc (HaplotypeCaller)"
      else { step = c; sub(/_$/, "", step) }
      printf fmt, $1, $2, $3, $4, $5, $6, step, (($1 in m) ? m[$1] : "?")
    }'
    rm -f $map
end
