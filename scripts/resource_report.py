#!/usr/bin/env python3
"""Per-step memory / time / CPU use for a finished (or partly finished) run.

Usage (from any folder, with the snparcher conda env active):
    python /projects/cts/jamie/vcf_pipeline/scripts/resource_report.py /projects/cts/jamie/runs/<run_name>

Reads snpArcher's benchmark files (one per job: peak memory, wall time, CPU
time), works out which step (rule) each belongs to, and compares them with
what the run's profile asked SLURM for. Writes:
    <run>/resource_report.tsv            one row per step
    <run>/suggested_set_resources.yaml   paste-able set-resources block

Suggested memory aims for ~60% average use (the middle of 50-70%), while
making sure the single biggest job still fits with ~10% to spare. Suggested
runtime is 1.5x the longest job plus 10 minutes.
"""
import csv
import math
import re
import statistics
import sys
from pathlib import Path

import yaml

PIPE = Path(__file__).resolve().parent.parent
TARGET_USE = 0.60       # aim for 60% of the request on a typical (95th percentile) job
MAX_USE = 0.90          # the biggest job must stay under 90% of the request
MIN_MEM = 1000          # MB


def rule_benchmark_patterns(snparcher):
    """{rule: regex} from the benchmark: lines in snpArcher's rule files."""
    pats = {}
    files = list((snparcher / "workflow").rglob("*.smk")) + list((snparcher / "workflow").rglob("Snakefile"))
    bench = re.compile(r"^\s*benchmark:\s*(?:\n\s*)?[\"']([^\"']+)[\"']", re.M)
    for f in files:
        text = f.read_text()
        starts = [(m.start(), m.group(1)) for m in re.finditer(r"^\s*(?:rule|checkpoint)\s+(\w+)\s*:", text, re.M)]
        for i, (pos, name) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
            m = bench.search(text, pos, end)
            if not m:
                continue
            p = m.group(1)
            parts = re.split(r"(\{[^}]+\})", p)
            strict = "".join("[^/]+" if x.startswith("{") else re.escape(x) for x in parts)
            loose = "".join(".+" if x.startswith("{") else re.escape(x) for x in parts)
            # module rules are imported with a prefix (qc_*, postprocess_*)
            prefix = ""
            if "modules/qc" in str(f):
                prefix = "qc_"
            elif "modules/postprocess" in str(f):
                prefix = "postprocess_"
            pats[prefix + name] = (re.compile("^" + strict + "$"), re.compile("^" + loose + "$"))
    return pats


def eval_res(v, attempt=1):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(eval(str(v), {"__builtins__": {}}, {"attempt": attempt}))
    except Exception:
        return None


def requests(profile):
    dr = profile.get("default-resources", {}) or {}
    sr = profile.get("set-resources", {}) or {}
    st = profile.get("set-threads", {}) or {}

    def get(rule):
        r = dict(dr)
        r.update(sr.get(rule, {}) or {})
        return {"mem_mb": eval_res(r.get("mem_mb")),
                "mem_mb_reduced": eval_res(r.get("mem_mb_reduced")),
                "runtime": eval_res(r.get("runtime")),
                "threads": int(st.get(rule, 1))}
    return get


def read_bench(f):
    try:
        rows = list(csv.DictReader(open(f), delimiter="\t"))
    except Exception:
        return None
    if not rows:
        return None
    r = rows[-1]
    try:
        return {"s": float(r["s"]), "rss": float(r["max_rss"]) if r["max_rss"] not in ("", "NA", "-") else None,
                "cpu": float(r["cpu_time"]) if r.get("cpu_time") not in (None, "", "NA", "-") else None}
    except (KeyError, ValueError):
        return None


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def roundup(x, step):
    return int(math.ceil(x / step) * step)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    run = Path(sys.argv[1]).resolve()
    prof_file = run / "profile" / "config.yaml"
    if not prof_file.exists():
        sys.exit(f"no profile at {prof_file} - is this a run folder?")
    profile = yaml.safe_load(open(prof_file))
    req = requests(profile)
    groups = profile.get("groups", {}) or {}
    import os
    pats = rule_benchmark_patterns(Path(os.environ.get("SNPARCHER_DIR", PIPE / "snpArcher")))

    by_rule, unmatched = {}, 0
    for f in sorted((run / "benchmarks").rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(run))
        rule = (next((r for r, (st, _) in pats.items() if st.match(rel)), None)
                or next((r for r, (_, lo) in pats.items() if lo.match(rel)), None))
        b = read_bench(f)
        if b is None:
            continue
        if rule is None:
            unmatched += 1
            continue
        by_rule.setdefault(rule, []).append(b)

    if not by_rule:
        sys.exit(f"no benchmark files found under {run / 'benchmarks'}")

    rows, suggest = [], {}
    for rule in sorted(by_rule):
        bs = by_rule[rule]
        r = req(rule)
        rss = [b["rss"] for b in bs if b["rss"] is not None]
        secs = [b["s"] for b in bs]
        cpu_eff = [b["cpu"] / (b["s"] * r["threads"]) for b in bs if b["cpu"] is not None and b["s"] > 0]
        mem = r["mem_mb"]
        use = [x / mem for x in rss] if (mem and rss) else []
        p95 = pct(rss, 0.95) if rss else None
        mx = max(rss) if rss else None
        sug_mem = None
        if rss:
            sug_mem = max(MIN_MEM, roundup(p95 / TARGET_USE, 500), roundup(mx / MAX_USE, 500))
        sug_rt = roundup(max(secs) * 1.5 / 60 + 10, 10)
        java = r["mem_mb_reduced"] is not None and rule in (profile.get("set-resources") or {}) \
            and "mem_mb_reduced" in (profile["set-resources"][rule] or {})
        flag = ""
        if use:
            med = statistics.median(use)
            flag = "LOW" if med < 0.5 else ("HIGH" if med > 0.7 else "ok")
            if max(use) > 0.95:
                flag += " near-limit"
        rows.append({
            "rule": rule, "group": groups.get(rule, ""), "jobs": len(bs), "threads": r["threads"],
            "req_mem_mb": int(mem) if mem else "NA",
            "median_rss_mb": round(statistics.median(rss)) if rss else "NA",
            "p95_rss_mb": round(p95) if p95 else "NA",
            "max_rss_mb": round(mx) if mx else "NA",
            "median_mem_use_pct": round(100 * statistics.median(use)) if use else "NA",
            "max_mem_use_pct": round(100 * max(use)) if use else "NA",
            "mem_flag": flag or "NA",
            "suggested_mem_mb": sug_mem or "NA",
            "req_runtime_min": int(r["runtime"]) if r["runtime"] else "NA",
            "median_runtime_min": round(statistics.median(secs) / 60, 1),
            "max_runtime_min": round(max(secs) / 60, 1),
            "suggested_runtime_min": sug_rt,
            "cpu_efficiency_pct": round(100 * statistics.median(cpu_eff)) if cpu_eff else "NA",
            "java_heap_limited": "yes" if java else "",
        })
        if sug_mem:
            s = {"mem_mb": f"attempt * {sug_mem}", "runtime": f"attempt * {sug_rt}"}
            if java:
                s["mem_mb_reduced"] = f"attempt * {int(sug_mem * 0.85)}"
            suggest[rule] = s

    out = run / "resource_report.tsv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    sy = run / "suggested_set_resources.yaml"
    with open(sy, "w") as f:
        f.write("# Suggested from benchmarks in " + str(run) + "\n"
                "# Review, then copy the rules you want into templates/profile.yaml set-resources.\n"
                "# Java (GATK) steps: memory use is capped by mem_mb_reduced (the -Xmx heap), so a\n"
                "# low % there can also mean the heap was simply big enough; lower both together.\n")
        yaml.safe_dump({"set-resources": suggest}, f, sort_keys=False)

    cols = ["rule", "jobs", "req_mem_mb", "max_rss_mb", "median_mem_use_pct", "mem_flag",
            "suggested_mem_mb", "max_runtime_min", "req_runtime_min", "suggested_runtime_min",
            "cpu_efficiency_pct"]
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(width[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(width[c]) for c in cols))
    print(f"\nmem_flag: LOW = typical job uses <50% of its request, HIGH = >70%, ok = 50-70%")
    if unmatched:
        print(f"({unmatched} benchmark files did not match a known rule and were skipped)")
    print(f"\nwrote {out}\nwrote {sy}")


if __name__ == "__main__":
    main()
