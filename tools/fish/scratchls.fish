# scratchls: what the pipeline has in its working folder (output_root, e.g. /scratch),
# how big each run is, and whether its results were copied to keep_results_root.
# Installed by tools/fish/install.sh
function scratchls --description 'List pipeline runs in the working (scratch) folder: scratchls'
    if test -z "$CTS_RUNS_DIR"
        echo "CTS_RUNS_DIR is not set - run: bash <pipeline folder>/tools/fish/install.sh"
        return 1
    end
    set -l root $CTS_RUNS_DIR
    if not test -d $root
        echo "nothing yet: $root does not exist"
        return 0
    end
    set -l runs $root/*/
    if test (count $runs) -eq 0
        echo "$root is empty"
        return 0
    end
    set -l queue (squeue -u $USER -h -o %j 2>/dev/null)
    set -l now (date +%s)
    set -l fmt "%-28s %8s %8s  %-11s %s\n"
    echo "Working folder: $root   (sizes take a moment)"
    printf $fmt RUN SIZE BAMS "LAST USED" STATUS
    for d in $runs
        set -l name (basename $d)
        set -l size (du -sh $d 2>/dev/null | cut -f1)
        set -l bams "-"
        test -d $d/results/bams; and set bams (du -sh $d/results/bams 2>/dev/null | cut -f1)
        set -l t (stat -c %Y $d 2>/dev/null)
        test -f $d/pipeline_console.log; and set t (stat -c %Y $d/pipeline_console.log)
        test -f $d/logs/pipeline_console.log; and set t (stat -c %Y $d/logs/pipeline_console.log)
        set -l days (math "floor(($now - $t) / 86400)")
        set -l state "results NOT copied - keep it"
        if contains -- ctl_$name $queue
            set state "RUNNING - do not delete"
        else if test -f $d/COPIED_TO.txt
            set state "results copied to "(head -1 $d/COPIED_TO.txt)
        end
        printf $fmt (string sub -l 28 -- $name) $size $bams "$days days" $state
    end
    echo
    echo "Scratch files untouched for 90 days are deleted automatically by ARC."
    echo "Remove a run:        scratchrm <run>"
    echo "Remove only its BAMs: scratchrm <run> --bams-only"
end
