# checkrun <run_name>: did the run finish, how good is the VCF, how efficiently did it use ARC.
# Writes everything to <run folder>/run_check.txt (send that file to Claude).
# Installed by tools/fish/install.sh (needs CTS_RUNS_DIR etc. from ~/.config/fish/conf.d/cts_pipeline.fish)
function checkrun --description 'Completion, VCF quality and resource use for a run: checkrun <run_name>'
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
    set -l pipe $CTS_PIPELINE_DIR
    set -l envpy $CTS_ENV_DIR/bin/python
    if test (count $argv) -lt 1
        echo "usage: checkrun <run_name>"
        echo "runs: "(ls $root | string join ' ')
        return 1
    end
    set -l name $argv[1]
    set -l run $root/$name
    set -l log $run/pipeline_console.log
    if not test -d $run
        echo "no run folder: $run"
        return 1
    end
    set -l out $run/run_check.txt

    # bcftools: on PATH, or from the pipeline's conda environments
    set -l bcf (command -s bcftools)
    if test -z "$bcf"
        set -l c $pipe/conda_envs/*/bin/bcftools
        set bcf $c[1]
    end

    begin
        echo "######## RUN CHECK: $name   ("(date)")"

        echo; echo "======== 1. DID IT FINISH?"
        if test -f $log
            echo "last progress line: "(grep -oE '[0-9]+ of [0-9]+ steps \([0-9.]+%\) done' $log | tail -1)
            set -l nerr (grep -c "Error in rule" $log)
            echo "'Error in rule' lines in log: $nerr"
            if test $nerr -gt 0
                grep -oE "Error in rule [A-Za-z_]+" $log | sort | uniq -c
            end
            grep -m3 -iE "Complete log|Nothing to be done|Exiting because a job execution failed" $log | string replace -r '\r$' ''
        else
            echo "no pipeline_console.log"
        end
        echo; echo "-- output files"
        ls -lh $run/results/vcfs/ 2>/dev/null
        for f in $run/results/qc/*.html $run/results/qc_metrics/*.tsv $run/*depth*.tsv $run/results/*depth*
            test -e $f; and ls -lh $f
        end

        echo; echo "======== 2. VCF QUALITY"
        if test -z "$bcf"
            echo "bcftools not found - skipping VCF checks"
        else
            set -l targets $run/config/targets_sorted.bed
            for v in $run/results/vcfs/*.vcf.gz
                echo; echo "---- "(basename $v)
                echo "samples: "($bcf view -h $v | tail -1 | awk '{ print NF - 9 }')
                echo "records: "($bcf view -H $v | count)
                echo "FILTER values (count):"
                $bcf query -f '%FILTER\n' $v | sort | uniq -c | sort -rn | head -15
                echo "passing SNPs (PASS or .):   "($bcf view -H -f .,PASS -v snps $v | count)
                echo "passing indels (PASS or .): "($bcf view -H -f .,PASS -v indels $v | count)
                if test -f $targets
                    echo "records outside target BED (should be 0): "($bcf view -H -T ^$targets $v | count)
                end
                echo "site depth (INFO/DP) of passing SNPs - min / median / mean / max:"
                $bcf query -i '(FILTER="PASS" || FILTER=".") && TYPE="snp"' -f '%INFO/DP\n' $v | sort -n | awk '
                    { a[NR] = $1; s += $1 } END { if (NR) printf "    %d / %d / %.1f / %d\n", a[1], a[int((NR + 1) / 2)], s / NR, a[NR]; else print "    none" }'
                $bcf stats -s - -f .,PASS $v > $run/.vcfstats.tmp
                echo "summary (passing sites):"
                grep -E "^SN" $run/.vcfstats.tmp | cut -f3- | string replace -r '^' '    '
                echo "Ts/Tv (passing): "(grep -E "^TSTV" $run/.vcfstats.tmp | cut -f5 | head -1)
                echo "per sample (passing sites): sample  hom_ref  hom_alt  het  het/hom_alt  mean_depth  missing  missing_%"
                grep -E "^PSC" $run/.vcfstats.tmp | awk -F'\t' '
                    { tot = $4 + $5 + $6 + $14; printf "    %-12s %8d %8d %8d %8s %8.1f %8d %8.1f\n", $3, $4, $5, $6, ($5 ? sprintf("%.2f", $6 / $5) : "NA"), $10, $14, (tot ? 100 * $14 / tot : 0) }'
                rm -f $run/.vcfstats.tmp
            end
        end

        echo; echo "======== 3. SAMPLE QC TABLE"
        set -l ss $run/results/qc_metrics/sample_summary.tsv
        if test -f $ss
            column -t -s \t $ss
        else
            echo "(no results/qc_metrics/sample_summary.tsv)"
        end

        echo; echo "======== 4. RESOURCE USE PER STEP (benchmarks)"
        if test -x $envpy
            $envpy $pipe/scripts/resource_report.py $run 2>&1
        else
            python3 $pipe/scripts/resource_report.py $run 2>&1
        end

        echo; echo "======== 5. SLURM JOBS (sacct, this run)"
        set -l ids (grep -oE "SLURM jobid [0-9]+|external jobid '[0-9]+'" $log 2>/dev/null | string match -r '[0-9]+' | sort -u | string join ',')
        if test -n "$ids"
            echo "SLURM jobs submitted: "(string split ',' $ids | count)
            sacct -j $ids -X --units=G -P \
                --format=JobID,State,Elapsed,Timelimit,AllocCPUS,TotalCPU,ReqMem,NodeList 2>/dev/null
            echo; echo "-- seff summary"
            for id in (string split ',' $ids)
                set -l e (seff $id 2>/dev/null | grep -E "State|Wall-clock|CPU Efficiency|Memory Utilized|Memory Efficiency" | string replace -r '^\s*' '' | string join ' | ')
                echo "$id | $e"
            end
        else
            echo "no SLURM job IDs found in the log"
        end
        for f in $run/efficiency_report*.csv $run/.snakemake/*efficiency*.csv
            test -f $f; and begin; echo; echo "-- plugin efficiency report: $f"; cat $f; end
        end
    end 2>&1 | tee $out

    echo
    echo "Saved: $out"
    set -l html $run/results/qc/*.html
    if test (count $html) -gt 0
        echo "QC dashboard (copy to your Mac to open): $html[1]"
    else
        echo "QC dashboard: not made (results/qc/*.html missing)"
    end
end
