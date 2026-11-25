# runstatus <run_name>: progress of a CTS VCF pipeline run, by step.
# Installed by tools/fish/install.sh (needs CTS_RUNS_DIR etc. from ~/.config/fish/conf.d/cts_pipeline.fish)
function runstatus --description 'Progress of a CTS pipeline run: runstatus <run_name>'
    if test -z "$CTS_RUNS_DIR"
        echo "CTS_RUNS_DIR is not set - run: bash <pipeline folder>/tools/fish/install.sh"
        return 1
    end
    set -l root $CTS_RUNS_DIR
    # finished runs whose working folder was cleaned from scratch: use the kept copy
    if test (count $argv) -ge 1; and not test -d $root/$argv[1]; and test -n "$CTS_KEEP_DIR"; and test -d $CTS_KEEP_DIR/$argv[1]
        set root $CTS_KEEP_DIR
        echo "(working folder gone from $CTS_RUNS_DIR - showing the kept copy in $CTS_KEEP_DIR)"
    end
    if test (count $argv) -lt 1
        echo "usage: runstatus <run_name>"
        echo "runs: "(ls $root | string join ' ')
        return 1
    end
    set -l run $root/$argv[1]
    set -l log $run/logs/pipeline_console.log
    test -f $log; or set log $run/pipeline_console.log   # older runs
    if not test -f $log
        echo "no log found: $log"
        return 1
    end
    set -l ns 0
    test -f $run/config/samples.csv; and set ns (math (count < $run/config/samples.csv) - 1)
    set -l nhc 0
    test -f $run/results/intervals/gvcf/intervals.txt; and set nhc (count < $run/results/intervals/gvcf/intervals.txt)
    set -l ndb 0
    test -f $run/results/intervals/db/intervals.txt; and set ndb (count < $run/results/intervals/db/intervals.txt)

    echo "Run: $argv[1]   ($ns samples)"
    awk -v ns=$ns -v nhc=$nhc -v ndb=$ndb '
function stage(r) {
  if (r ~ /^fastp|collect_fastp/) return 1
  if (r ~ /bwa|markdup|merge_library|merge_dedup|index_bam|bam_stats/) return 2
  if (r ~ /haplotypecaller|concat_interval_gvcfs/) return 3
  if (r ~ /db_mapfile|genomics_db|genotype_gvcfs|concat_interval_vcfs|variant_filtration|compress_/) return 4
  if (r ~ /mosdepth|clam|callable|coverage_bed|qc_|combine_qc/) return 5
  return 0
}
{ sub(/\r$/, "") }   # screen logs end lines with \r
/^Job stats:/ { delete tot; delete done; delete err; intab=1; skip=2; next }
intab && skip > 0 { skip--; next }
intab { if ($1 == "total" || NF < 2) { intab=0 } else { tot[$1]=$2 }; next }
/Finished jobid: [0-9]+ \(Rule: / { r=$0; sub(/.*\(Rule: /, "", r); sub(/\).*/, "", r); done[r]++ }
/^[ \t]*Error in rule / { r=$0; sub(/.*Error in rule /, "", r); sub(/:.*/, "", r); err[r]++ }
/ steps \([0-9.]+%\) done/ { overall=$0; sub(/^.*\] */, "", overall) }
END {
  # chunk jobs only appear after the interval step, so fill in expected totals
  if (nhc > 0 && !("gatk_haplotypecaller_interval" in tot)) tot["gatk_haplotypecaller_interval"] = ns * nhc
  if (nhc > 0 && !("concat_interval_gvcfs" in tot)) tot["concat_interval_gvcfs"] = ns
  if (ndb > 0 && !("gatk_genomics_db_import" in tot)) tot["gatk_genomics_db_import"] = ndb
  if (ndb > 0 && !("gatk_genotype_gvcfs" in tot)) tot["gatk_genotype_gvcfs"] = ndb
  for (r in done) if (!(r in tot)) tot[r] = "?"
  name[0]="Setup (reference, intervals)"; name[1]="1 Read trimming"; name[2]="2 Mapping + duplicates"
  name[3]="3 Variant calling (HaplotypeCaller)"; name[4]="4 Joint genotyping + filtering -> VCF"
  name[5]="Callable sites + QC"
  printf "Overall: %s\n", (overall ? overall : "no progress line yet")
  for (s = 0; s <= 5; s++) {
    n = 0; st = 0; sd = 0
    for (r in tot) if (r != "all" && stage(r) == s) { n++; if (tot[r] != "?") { st += tot[r]; sd += (done[r] < tot[r] ? done[r] : tot[r]) } }
    if (!n) continue
    printf "\n%-40s %s\n", name[s], (st ? sprintf("%d/%d  %3d%%", sd, st, 100*sd/st) : "")
    for (r in tot) if (r != "all" && stage(r) == s) {
      t = tot[r]; d = done[r] + 0
      pct = (t == "?" || t == 0) ? "  ?" : sprintf("%3d", 100 * (d < t ? d : t) / t)
      printf "    %-34s %5d / %-5s %s%%%s\n", r, d, t, pct, (err[r] ? sprintf("   %d ERROR(S)", err[r]) : "")
    }
  }
}
' $log

    echo
    echo "SLURM jobs now:"
    set -l q (squeue -u $USER -h -o %T | sort | uniq -c | string trim)
    if test (count $q) -gt 0
        printf '    %s\n' $q
    else
        echo "    none in queue"
    end
    set -l vcfs $run/results/vcfs/*.vcf.gz
    if test (count $vcfs) -gt 0
        echo
        echo "VCF(s):"
        printf '    %s\n' $vcfs
    end
end
