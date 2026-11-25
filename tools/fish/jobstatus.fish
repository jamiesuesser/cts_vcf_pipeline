# jobstatus <run_name>: what each queued/running SLURM job of a run is doing right now.
# Installed by tools/fish/install.sh (needs CTS_RUNS_DIR etc. from ~/.config/fish/conf.d/cts_pipeline.fish)
function jobstatus --description 'Progress inside each running job of a run: jobstatus <run_name>'
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
        # runs going right now = queued/running controller jobs (named ctl_<run_name>)
        set -l active (squeue -u $USER -h -o %j 2>/dev/null | string match -r '^ctl_.+' | string replace ctl_ '' | sort -u)
        if test (count $active) -eq 1
            set argv $active
            echo "($active is the only run going - showing it)"
        else
            echo "usage: jobstatus <run_name>"
            if test (count $active) -eq 0
                echo "no runs going right now (finished runs can still be named)"
            else
                echo "runs going: "(string join ' ' $active)
            end
            return 1
        end
    end
    set -l run $root/$argv[1]
    set -l log $run/logs/pipeline_console.log
    test -f $log; or set log $run/pipeline_console.log   # older runs
    if not test -f $log
        echo "no log found: $log"
        return 1
    end
    set -l queue (squeue -u $USER -h -o "%i|%T|%M")
    set -l fmt "%-9s %-8s %9s  %-30s %-22s %s\n"
    printf $fmt JOBID STATE TIME "SAMPLE(S)" STEP PROGRESS
    set -l n 0
    for sub in (grep -oE "SLURM jobid [0-9]+ \(log: [^)]*|external jobid '[0-9]+'" $log | string replace -r '\r$' '' | sort -u)
        set -l id (string match -r '\d+' $sub)
        set -l f $run/logs/slurm/$id.out
        set -l m (string match -r 'SLURM jobid (\d+) \(log: (.*)' $sub)
        test (count $m) -ge 3; and set f $m[3]
        string match -q '/*' $f; or set f $run/$f
        set -l q (string match -r "^$id\|.*" $queue)
        test -n "$q"; or continue            # finished jobs are no longer in the queue
        set -l qq (string split '|' $q)
        set n (math $n + 1)
        set -l samples -
        set -l step -
        set -l pct "not started"
        if test -f $f
            set -l s (grep -oE "sample=[^,' ]+" $f | string replace 'sample=' '' | sort -u | string join ',')
            test -n "$s"; and set samples $s
            set -l r (grep -oE '^\s*(local)?rule [A-Za-z_]+:' $f | tail -1 | string trim | string replace -r '^(local)?rule ' '' | string replace ':' '')
            test -n "$r"; and set step $r
            set -l p (grep -oE '[0-9]+ of [0-9]+ steps \([0-9.]+%\) done' $f | tail -1)
            if test -n "$p"
                set pct $p
            else if test -n "$r"
                set pct "0 steps done"
            end
        end
        printf $fmt $id $qq[2] $qq[3] (string sub -l 30 -- $samples) $step $pct
    end
    test $n -gt 0; or echo "(no jobs from $argv[1] in the queue)"
end
