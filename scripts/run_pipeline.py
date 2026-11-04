#!/usr/bin/env python3
"""CTS VCF pipeline driver.

Reads edit_me_before_running.yaml, builds a run folder (sample sheet, snpArcher
config, SLURM profile), reuses the pre-indexed reference, runs snpArcher, then
computes per-sample on-target depth and merges it into snpArcher's QC report.
"""
import argparse
import csv
import gzip
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import RunMonitor, send_email  # noqa: E402

PIPE = Path(__file__).resolve().parent.parent
SETTINGS = PIPE / "edit_me_before_running.yaml"
SNAKEFILE = PIPE / "snpArcher" / "workflow" / "Snakefile"
TARGETS_BED = PIPE / "reference" / "targets_sorted.bed"
REF_FASTA = PIPE / "reference" / "Axo_Ref.fna"
PREPARED_REF = PIPE / "reference" / "prepared"
CONDA_PREFIX = PIPE / "conda_envs"


def die(msg):
    sys.exit(f"\nERROR: {msg}\n")


def say(msg):
    print(f"[vcf_pipeline] {msg}", flush=True)


# ---------------------------------------------------------------- settings
def load_settings():
    global TARGETS_BED, REF_FASTA, PREPARED_REF
    with open(SETTINGS) as f:
        s = yaml.safe_load(f) or {}
    # Reference files: settings override the defaults in vcf_pipeline/reference/
    if s.get("reference_fasta"):
        REF_FASTA = Path(s["reference_fasta"])
    if s.get("reference_index_dir"):
        PREPARED_REF = Path(s["reference_index_dir"])
    if s.get("targets_bed"):
        TARGETS_BED = Path(s["targets_bed"])
    for k in ["run_name", "output_root", "raw_fastq_dirs", "slurm_account", "slurm_partition"]:
        if not s.get(k):
            die(f"'{k}' is empty in {SETTINGS}")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(s["run_name"])):
        die("run_name may only contain letters, numbers, . _ -")
    for p in [SNAKEFILE, TARGETS_BED, REF_FASTA, PIPE / "templates" / "config.yaml",
              PIPE / "templates" / "profile.yaml"]:
        if not p.exists():
            die(f"file not found: {p}")
    return s


# ---------------------------------------------------------------- metadata
def hbs_of(sample_id):
    """HBS number = leading digits of the sample ID (104935R -> 104935)."""
    m = re.match(r"\d+", sample_id)
    return m.group(0) if m else sample_id


def norm_hbs(v):
    v = str(v).strip()
    return v[:-2] if re.fullmatch(r"\d+\.0", v) else v


def load_metadata(s):
    """Return (columns, {hbs: {col: value}}) or (None, {}) if no metadata file."""
    path = s.get("metadata_file")
    if not path:
        return None, {}
    path = Path(path)
    if not path.exists():
        die(f"metadata_file not found: {path}")
    if path.suffix.lower() in (".xlsx", ".xls"):
        die("metadata_file must be .csv or .tsv - save the spreadsheet as CSV first")
    delim = "\t" if path.suffix.lower() in (".tsv", ".txt") else ","
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delim)
        cols = [c for c in (reader.fieldnames or [])]
        hcol = s.get("metadata_hbs_column", "HBS")
        if hcol not in cols:
            die(f"column '{hcol}' not in {path}. Columns found: {', '.join(cols)}")
        meta = {}
        for row in reader:
            key = norm_hbs(row.get(hcol, ""))
            if key:
                meta[key] = row
    return cols, meta


def write_snparcher_metadata(s, run_dir, sample_ids, meta):
    """snpArcher sample_metadata.csv (sample_id,lat,long) for the QC map, if lat/long set."""
    lat, lon = s.get("metadata_lat_column"), s.get("metadata_long_column")
    if not (meta and lat and lon):
        return None
    out = run_dir / "config" / "sample_metadata.csv"
    with open(out, "w") as f:
        f.write("sample_id,lat,long\n")
        for sid in sample_ids:
            row = meta.get(hbs_of(sid))
            if row and row.get(lat, "").strip() and row.get(lon, "").strip():
                f.write(f"{sid},{row[lat].strip()},{row[lon].strip()}\n")
    return out


# ------------------------------------------------------------ sample sheet
def build_sample_sheet(s, out_csv):
    dirs = s["raw_fastq_dirs"]
    if isinstance(dirs, str):
        dirs = [dirs]
    exclude = {str(x) for x in (s.get("exclude_samples") or [])}
    rows, skipped = [], []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            die(f"raw FASTQ folder not found: {d}")
        for r1 in sorted(d.glob("*_R1_001.fastq.gz")):
            sample = r1.name.split("_")[0]
            if sample.lower() == "undetermined":
                continue
            if sample in exclude:
                skipped.append(sample)
                continue
            r2 = r1.with_name(r1.name.replace("_R1_001", "_R2_001", 1))
            if not r2.exists():
                say(f"WARNING: no R2 for {r1.name}, skipping")
                continue
            if not re.fullmatch(r"[A-Za-z0-9._-]+", sample):
                die(f"sample ID '{sample}' has characters snpArcher won't accept")
            rows.append((sample, f"{r1.resolve()};{r2.resolve()}"))
    if not rows:
        die("no *_R1_001.fastq.gz files found in raw_fastq_dirs")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w") as f:
        f.write("sample_id,input_type,input\n")
        for sample, inp in rows:
            f.write(f"{sample},fastq,{inp}\n")
    sample_ids = sorted({r[0] for r in rows})
    say(f"sample sheet: {len(sample_ids)} samples ({len(rows)} read pairs) -> {out_csv}")
    if skipped:
        say(f"excluded: {', '.join(sorted(set(skipped)))}")
    return sample_ids


# ----------------------------------------------------------------- configs
def put(d, key, val):
    if val is not None and val != "":
        d[key] = val


def render_config(s, run_dir, samples_csv, metadata_csv):
    with open(PIPE / "templates" / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["samples"] = str(samples_csv)
    cfg["targets_bed"] = str(TARGETS_BED)
    ref = cfg.setdefault("reference", {})
    ref["source"] = str(REF_FASTA)
    ref["name"] = ref_name(s)

    vc = cfg.setdefault("variant_calling", {})
    put(vc, "expected_coverage", s.get("expected_coverage"))
    put(vc, "ploidy", s.get("ploidy"))
    put(vc.setdefault("gatk", {}), "het_prior", s.get("het_prior"))

    cs = cfg.setdefault("callable_sites", {})
    cov = cs.setdefault("coverage", {})
    put(cov, "fraction", s.get("callable_fraction"))
    put(cov, "min_coverage", s.get("callable_min_coverage"))
    put(cov, "max_coverage", s.get("callable_max_coverage"))
    put(cs.setdefault("mappability", {}), "enabled", s.get("mappability_filter"))

    put(cfg.setdefault("intervals", {}), "min_contig_length", s.get("min_contig_length"))

    mods = cfg.setdefault("modules", {})
    put(mods.setdefault("qc", {}), "enabled", s.get("qc_module"))
    pp = mods.setdefault("postprocess", {})
    put(pp, "enabled", s.get("postprocess_module"))
    filt = pp.setdefault("filtering", {})
    put(filt, "maf", s.get("postprocess_maf"))
    put(filt, "missingness", s.get("postprocess_missingness"))
    put(filt, "contig_size", s.get("postprocess_contig_size"))
    if "postprocess_exclude_scaffolds" in s:
        filt["exclude_scaffolds"] = s.get("postprocess_exclude_scaffolds") or ""

    if metadata_csv:
        cfg["sample_metadata"] = str(metadata_csv)
    else:
        cfg.pop("sample_metadata", None)

    out = run_dir / "config" / "config.yaml"
    with open(out, "w") as f:
        f.write("# GENERATED by vcf_pipeline/run_pipeline.py - edit edit_me_before_running.yaml instead\n")
        yaml.safe_dump(cfg, f, sort_keys=False)
    return out


def render_profile(s, run_dir):
    with open(PIPE / "templates" / "profile.yaml") as f:
        prof = yaml.safe_load(f)
    dr = prof.setdefault("default-resources", {})
    dr["slurm_account"] = s["slurm_account"]
    dr["slurm_partition"] = s["slurm_partition"]
    prof["jobs"] = int(s.get("max_jobs", 100))
    prof["retries"] = int(s.get("retries", 2))
    prof["keep-going"] = True
    prof["rerun-incomplete"] = True
    prof["conda-prefix"] = str(CONDA_PREFIX)
    # Rerun on file timestamps only, so the shared pre-indexed reference is reused
    prof["rerun-triggers"] = ["mtime"]
    out = run_dir / "profile" / "config.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write("# GENERATED by vcf_pipeline/run_pipeline.py - edit edit_me_before_running.yaml or templates/profile.yaml\n")
        yaml.safe_dump(prof, f, sort_keys=False)
    return out.parent


INDEX_SUFFIXES = [".fa.gz", ".fa.gz.fai", ".fa.gz.gzi", ".dict", ".fa.gz.sa", ".fa.gz.pac",
                  ".fa.gz.bwt", ".fa.gz.ann", ".fa.gz.amb"]


def ref_name(s):
    return str(s.get("reference_name") or "Axo")


def index_files(folder, name):
    return [folder / f"{name}{x}" for x in INDEX_SUFFIXES]


def index_complete(folder, name):
    return all(p.exists() and p.stat().st_size > 0 for p in index_files(folder, name))


def stamp_ok(name):
    """True if the saved index was built from the current reference_fasta (by size)."""
    stamp = PREPARED_REF / f"{name}.index_info.txt"
    if not stamp.exists():
        return True  # older index without a stamp - trust it, stamp it now
    for line in stamp.read_text().splitlines():
        if line.startswith("reference_size:"):
            return int(line.split(":", 1)[1]) == REF_FASTA.stat().st_size
    return True


def write_stamp(name):
    PREPARED_REF.mkdir(parents=True, exist_ok=True)
    (PREPARED_REF / f"{name}.index_info.txt").write_text(
        f"reference_fasta: {REF_FASTA}\nreference_size: {REF_FASTA.stat().st_size}\n")


def link(src, dst):
    if dst.exists() or dst.is_symlink():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def stage_reference(s, run_dir):
    """Reuse a saved index if it matches the reference; otherwise snpArcher builds one."""
    name = ref_name(s)
    dst = run_dir / "results" / "reference"
    if index_complete(dst, name):
        say("reference index already in run folder")
        return True
    if not index_complete(PREPARED_REF, name):
        say(f"no saved index for '{name}' in {PREPARED_REF} - snpArcher will build it "
            "(~17 h, one time only; it is saved for future runs)")
        return False
    if not stamp_ok(name):
        say(f"WARNING: saved index in {PREPARED_REF} was built from a different reference - "
            "building a new one (~17 h); it will replace the old index")
        return False
    if not (PREPARED_REF / f"{name}.index_info.txt").exists():
        write_stamp(name)
    dst.mkdir(parents=True, exist_ok=True)
    for src in index_files(PREPARED_REF, name):
        link(src, dst / src.name)
    # Index must look newer than the reference FASTA, or Snakemake rebuilds it
    ref_t = REF_FASTA.stat().st_mtime
    staged = index_files(dst, name)
    if min(p.stat().st_mtime for p in staged) <= ref_t:
        os.utime(staged[0], (ref_t + 10, ref_t + 10))
        for p in staged[1:]:
            os.utime(p, (ref_t + 20, ref_t + 20))
    say(f"reusing saved reference index from {PREPARED_REF}")
    return True


def save_index(s, run_dir):
    """After a run that built the index, save it so later runs skip indexing."""
    name = ref_name(s)
    src = run_dir / "results" / "reference"
    if not index_complete(src, name):
        return
    if index_complete(PREPARED_REF, name) and stamp_ok(name):
        return
    PREPARED_REF.mkdir(parents=True, exist_ok=True)
    for f in index_files(src, name):
        t = PREPARED_REF / f.name
        if t.exists():
            t.unlink()
        link(f, t)
    write_stamp(name)
    say(f"reference index saved to {PREPARED_REF} - future runs will skip indexing")


# ---------------------------------------------------------------- target BED
def contig_order(s):
    """Contig names in reference order, from a .fai if available, else FASTA headers."""
    name = ref_name(s)
    for fai in [PREPARED_REF / f"{name}.fa.gz.fai", Path(str(REF_FASTA) + ".fai")]:
        if fai.exists():
            return [line.split("\t", 1)[0] for line in open(fai) if line.strip()]
    cache = PREPARED_REF / f"{name}.contig_order.txt"
    if cache.exists() and stamp_ok(name):
        return cache.read_text().split()
    say("reading contig names from the reference FASTA (a few minutes, first run only)")
    opener = gzip.open if str(REF_FASTA).endswith(".gz") else open
    names = []
    with opener(REF_FASTA, "rt") as f:
        for line in f:
            if line.startswith(">"):
                names.append(line[1:].split()[0])
    PREPARED_REF.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(names) + "\n")
    return names


def prepare_targets(s, run_dir):
    """Check the target BED matches the reference and write a reference-sorted copy."""
    global TARGETS_BED
    order = {c: i for i, c in enumerate(contig_order(s))}
    rows, missing = [], set()
    for line in open(TARGETS_BED):
        if not line.strip() or line.startswith(("#", "track", "browser")):
            continue
        p = line.rstrip("\n").split("\t")
        if p[0] not in order:
            missing.add(p[0])
            continue
        rows.append((order[p[0]], int(p[1]), int(p[2]), line if line.endswith("\n") else line + "\n"))
    if missing:
        ex = ", ".join(sorted(missing)[:5])
        die(f"{len(missing)} contig name(s) in the target BED are not in the reference "
            f"(e.g. {ex}). The BED and reference are probably from different assemblies.")
    if not rows:
        die(f"no regions found in {TARGETS_BED}")
    sorted_rows = sorted(rows, key=lambda r: (r[0], r[1], r[2]))
    out = run_dir / "config" / "targets_sorted.bed"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.writelines(r[3] for r in sorted_rows)
    total = sum(r[2] - r[1] for r in rows)
    note = "already sorted" if sorted_rows == rows else "was not in reference order - sorted"
    say(f"target BED: {len(rows)} regions, {total/1e6:.1f} Mb, {note} -> {out}")
    TARGETS_BED = out


# -------------------------------------------------------------- snakemake
def run_snakemake(run_dir, profile_dir, extra, monitor=None):
    cmd = ["snakemake", "-s", str(SNAKEFILE), "-d", str(run_dir),
           "--workflow-profile", str(profile_dir)] + extra
    say("running: " + " ".join(cmd))
    if monitor is None:
        return subprocess.call(cmd)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        try:
            monitor.feed(line)
        except Exception as e:  # monitoring must never stop the run
            say(f"WARNING: monitor error ({e})")
    return proc.wait()


# ------------------------------------------------------------ depth summary
def find_mosdepth(run_dir):
    for base in [CONDA_PREFIX, run_dir / ".snakemake" / "conda"]:
        hits = sorted(base.glob("*/bin/mosdepth"))
        if hits:
            return str(hits[0])
    w = shutil.which("mosdepth")
    if w:
        return w
    return None


def run_depth(s, run_dir):
    global TARGETS_BED
    sorted_bed = run_dir / "config" / "targets_sorted.bed"
    if sorted_bed.exists():
        TARGETS_BED = sorted_bed
    bams = sorted((run_dir / "results" / "bams" / "markdup").glob("*.bam"))
    outd = run_dir / "results" / "ontarget_depth"
    min_depth = int(s.get("min_ontarget_depth", 10))
    if not bams:
        say("no BAMs yet - skipping depth step")
        return summarize(s, run_dir, outd, min_depth), False
    outd.mkdir(parents=True, exist_ok=True)
    failed = False
    todo = [b for b in bams if not (outd / f"{b.stem}.mosdepth.summary.txt").exists()]
    min_depth = int(s.get("min_ontarget_depth", 10))
    mosdepth = find_mosdepth(run_dir) if todo else None
    if todo and not mosdepth:
        say("WARNING: mosdepth not found - skipping on-target depth")
        todo = []
    if todo:
        lst = outd / "bams_to_run.txt"
        lst.write_text("\n".join(str(b) for b in todo) + "\n")
        conc = min(int(s.get("max_jobs", 100)), 50)
        cmd = ["sbatch", "--wait", "--parsable",
               "-A", s["slurm_account"], "-p", s["slurm_partition"],
               f"--array=1-{len(todo)}%{conc}",
               "-o", str(run_dir / "logs" / "slurm" / "ontarget_%A_%a.out"),
               str(PIPE / "scripts" / "ontarget_depth_array.sh"),
               str(lst), str(outd), str(TARGETS_BED), mosdepth,
               str(int(s.get("depth_min_mapq", 20))), str(min_depth)]
        say(f"on-target depth for {len(todo)} BAMs (waits until done)")
        if subprocess.call(cmd) != 0:
            say("WARNING: some depth jobs failed - see logs/slurm/ontarget_*.out")
            failed = True
    missing = [b.stem for b in bams if not (outd / f"{b.stem}.mosdepth.summary.txt").exists()]
    return summarize(s, run_dir, outd, min_depth), missing


def read_depth(outd):
    rows = {}
    for f in sorted(outd.glob("*.mosdepth.summary.txt")):
        sid = f.name[: -len(".mosdepth.summary.txt")]
        mean = None
        for line in open(f):
            p = line.rstrip("\n").split("\t")
            if p[0] == "total_region":
                mean = float(p[3])
        pct = None
        thr = outd / f"{sid}.thresholds.bed.gz"
        if thr.exists():
            tot = cov = 0
            with gzip.open(thr, "rt") as g:
                for line in g:
                    if line.startswith("#"):
                        continue
                    p = line.rstrip("\n").split("\t")
                    tot += int(p[2]) - int(p[1])
                    cov += int(p[4])
            pct = 100.0 * cov / tot if tot else 0.0
        rows[sid] = (mean, pct)
    return rows


def summarize(s, run_dir, outd, min_depth):
    """One table per run: sample, HBS, snpArcher QC, on-target depth, metadata."""
    qcdir = run_dir / "results" / "qc_metrics"
    qcdir.mkdir(parents=True, exist_ok=True)
    depth = read_depth(outd) if outd.is_dir() else {}

    qc_cols, qc = [], {}
    qcf = qcdir / "qc_report.tsv"
    if qcf.exists():
        with open(qcf) as f:
            r = csv.reader(f, delimiter="\t")
            hdr = next(r)
            qc_cols = hdr[1:]
            for row in r:
                if row:
                    qc[row[0]] = row[1:]

    sheet = run_dir / "config" / "samples.csv"
    samples = set(depth) | set(qc)
    if sheet.exists():
        with open(sheet) as f:
            samples |= {line.split(",")[0] for line in list(f)[1:] if line.strip()}
    if not samples:
        say("nothing to summarize yet")
        return None

    meta_cols, meta = load_metadata(s)
    hcol = s.get("metadata_hbs_column", "HBS")
    meta_cols = [c for c in (meta_cols or []) if c != hcol]

    dcol = f"pct_target_bases_ge_{min_depth}x"
    header = (["sample_id", "hbs_number"] + qc_cols +
              ["ontarget_mean_depth", dcol, "passes_min_depth"] + meta_cols)
    low, no_meta, means = [], [], []
    out = qcdir / "sample_summary.tsv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        for sid in sorted(samples, key=lambda x: (hbs_of(x), x)):
            hbs = hbs_of(sid)
            mean, pct = depth.get(sid, (None, None))
            if mean is not None:
                means.append(mean)
            ok = "NA" if mean is None else ("yes" if mean >= min_depth else "no")
            if ok == "no":
                low.append(sid)
            m = meta.get(hbs)
            if meta and m is None:
                no_meta.append(sid)
            w.writerow([sid, hbs] + qc.get(sid, ["NA"] * len(qc_cols)) +
                       ["NA" if mean is None else f"{mean:.2f}",
                        "NA" if pct is None else f"{pct:.1f}", ok] +
                       [(m or {}).get(c, "NA") for c in meta_cols])

    (qcdir / "low_depth_samples.txt").write_text("\n".join(low) + ("\n" if low else ""))
    say(f"sample summary: {out}")
    if means:
        say(f"depth: {len(means)} samples, mean on-target {sum(means)/len(means):.1f}x, "
            f"{len(low)} below {min_depth}x -> results/qc_metrics/low_depth_samples.txt")
    if meta:
        say(f"metadata linked by HBS for {len(samples) - len(no_meta)}/{len(samples)} samples")
        if no_meta:
            say(f"WARNING: no metadata row for: {', '.join(no_meta[:20])}"
                + (" ..." if len(no_meta) > 20 else ""))
    return {"summary": out, "n": len(means), "low": low, "no_meta": no_meta,
            "mean": (sum(means) / len(means)) if means else None, "min_depth": min_depth}


def email_depth(s, run_dir, info, missing):
    if not info:
        send_email(s, "Step 5/5 Depth summary: nothing to summarize", f"Run folder: {run_dir}")
        return
    low, md = info["low"], info["min_depth"]
    bad = bool(low or missing)
    subject = ("Step 5/5 Depth summary: done - pipeline finished"
               + (f", {len(low)} sample(s) below {md}x" if low else "")
               + (f", {len(missing)} depth job(s) FAILED" if missing else ""))
    body = [f"Run folder: {run_dir}",
            f"Samples with depth: {info['n']}",
            "Mean on-target depth: " + (f"{info['mean']:.1f}x" if info["mean"] is not None else "NA"),
            f"Below {md}x: {len(low)}", ""]
    if low:
        body += [f"  {x}" for x in low] + [""]
    if missing:
        body += ["Depth jobs FAILED for:"] + [f"  {x}" for x in missing] + [""]
    if info["no_meta"]:
        body += [f"No metadata row for: {', '.join(info['no_meta'])}", ""]
    body.append(f"Summary table: {info['summary']}")
    send_email(s, subject, "\n".join(body))


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="CTS VCF pipeline")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="show the plan, run nothing")
    g.add_argument("--prepare-only", action="store_true", help="build the run folder only")
    g.add_argument("--depth-only", action="store_true", help="only run the depth summary")
    g.add_argument("--unlock", action="store_true", help="clear a stale Snakemake lock")
    g.add_argument("--test-email", action="store_true", help="send a test email and stop")
    args = ap.parse_args()

    s = load_settings()
    run_dir = Path(s["output_root"]) / str(s["run_name"])
    (run_dir / "logs" / "slurm").mkdir(parents=True, exist_ok=True)
    say(f"run folder: {run_dir}")

    if args.test_email:
        if not s.get("notify_email"):
            die("notify_email is empty in the settings file")
        send_email(s, "Test email", f"Email notifications work for run folder {run_dir}.")
        return 0
    if args.depth_only:
        email_depth(s, run_dir, *run_depth(s, run_dir))
        return 0

    shutil.copy(SETTINGS, run_dir / "edit_me_used_for_this_run.yaml")
    samples_csv = run_dir / "config" / "samples.csv"
    sample_ids = build_sample_sheet(s, samples_csv)
    _, meta = load_metadata(s)
    metadata_csv = write_snparcher_metadata(s, run_dir, sample_ids, meta)
    prepare_targets(s, run_dir)
    render_config(s, run_dir, samples_csv, metadata_csv)
    profile_dir = render_profile(s, run_dir)
    stage_reference(s, run_dir)

    if args.prepare_only:
        say("prepared - nothing run")
        return 0
    if args.unlock:
        return run_snakemake(run_dir, profile_dir, ["--unlock"])
    if args.dry_run:
        return run_snakemake(run_dir, profile_dir, ["-n", "--quiet", "rules"])

    if not os.environ.get("STY") and not os.environ.get("TMUX"):
        say("WARNING: not inside screen - closing this terminal will stop the run")

    monitor = RunMonitor(s, run_dir, sample_ids)
    rc = run_snakemake(run_dir, profile_dir, [], monitor)
    save_index(s, run_dir)
    monitor.finish(rc)
    email_depth(s, run_dir, *run_depth(s, run_dir))
    vcfs = sorted((run_dir / "results" / "vcfs").glob("*.vcf.gz"))
    say("snpArcher " + ("finished OK" if rc == 0 else f"exited with errors (code {rc}) - check the log above"))
    for v in vcfs:
        say(f"VCF: {v}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
