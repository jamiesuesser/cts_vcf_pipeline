# scratchrm <run> [--bams-only]: delete a run's working folder (or just its BAMs) from the
# working folder (output_root, e.g. /scratch). Refuses while the run is going, warns if its
# results were never copied to keep_results_root, and always asks before deleting.
# Installed by tools/fish/install.sh
function scratchrm --description 'Delete a run (or its BAMs) from the working folder: scratchrm <run> [--bams-only]'
    if test -z "$CTS_RUNS_DIR"
        echo "CTS_RUNS_DIR is not set - run: bash <pipeline folder>/tools/fish/install.sh"
        return 1
    end
    if test -z "$CTS_KEEP_DIR"; or test "$CTS_KEEP_DIR" = "$CTS_RUNS_DIR"
        echo "keep_results_root is not set, so $CTS_RUNS_DIR holds your only copy of each run."
        echo "scratchrm only works when runs are copied elsewhere - delete by hand if you really mean to."
        return 1
    end
    if test (count $argv) -lt 1
        echo "usage: scratchrm <run> [--bams-only]     (see scratchls)"
        return 1
    end
    set -l name $argv[1]
    if string match -q -- '*/*' $name; or test "$name" = "." -o "$name" = ".."
        echo "give just the run name, as listed by scratchls"
        return 1
    end
    set -l d $CTS_RUNS_DIR/$name
    if not test -d $d
        echo "no run '$name' in $CTS_RUNS_DIR"
        return 1
    end
    if contains -- ctl_$name (squeue -u $USER -h -o %j 2>/dev/null)
        echo "$name is still running (job ctl_$name) - stop it first or wait until it finishes."
        return 1
    end
    set -l target $d
    set -l what "the whole run folder"
    if contains -- --bams-only $argv
        set target $d/results/bams
        set what "the BAMs only (VCFs, GVCFs and logs stay)"
        if not test -d $target
            echo "$name has no BAMs left."
            return 0
        end
    end
    echo "Run:    $name"
    echo "Delete: $what"
    echo "        $target  ("(du -sh $target 2>/dev/null | cut -f1)")"
    if test -f $d/COPIED_TO.txt
        echo "Kept copy of results: "(head -1 $d/COPIED_TO.txt)" ("(sed -n 2p $d/COPIED_TO.txt)")"
    else
        echo "WARNING: this run's results were NEVER copied to $CTS_KEEP_DIR."
        echo "         Deleting it loses its VCFs too. To copy them first: bash run_pipeline.sh --copy-results"
        echo "         (with run_name set to $name)"
    end
    read -P "Type yes to delete: " answer
    if test "$answer" != yes
        echo "Nothing deleted."
        return 1
    end
    rm -rf -- $target
    and echo "Deleted $target"
end
