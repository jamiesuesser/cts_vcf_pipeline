#!/usr/bin/env python3
"""Apply the CTS edits to a snpArcher checkout. Safe to run more than once.

Usage:  python patch_snparcher.py /projects/cts/jamie/vcf_pipeline/snpArcher

Edits (see SNParcher_changes.md section 1):
  1a  HaplotypeCaller also gets -L targets_bed with --interval-set-rule INTERSECTION
  1b  config schema accepts the targets_bed key
  1c  the interval list that gVCF and GenomicsDB chunks are cut from is built
      from targets_bed (BedToIntervalList) instead of the whole genome
      (ScatterIntervalsByNs). Every chunk then contains targets, so no
      HaplotypeCaller job gets an empty intersection, and joint genotyping
      only runs over the targets.
  1d  QC dashboard: if no sample passes the dashboard's depth cutoff, keep all
      samples instead of handing PLINK an empty VCF (which stops the run)
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
changed = []


def die(msg):
    sys.exit(f"ERROR: {msg} - edit it by hand (see SNParcher_changes.md)")


# ---- 1a: HaplotypeCaller restricted to the targets --------------------------
smk = root / "workflow/rules/variant_calling/gatk_intervals.smk"
s = smk.read_text()
start = s.index("rule gatk_haplotypecaller_interval:")
end = s.find("\nrule ", start + 1)
end = len(s) if end == -1 else end
rule = s[start:end]
if "params.targets" not in rule:
    p_old = re.search(r"^(\s+)min_dangling=.*,\n", rule, re.M)
    l_old = re.search(r"^(\s+)-L \{input\.interval\} \\\n", rule, re.M)
    if not p_old or not l_old:
        die(f"{smk} is not in the expected form")
    ind_p, ind_l = p_old.group(1), l_old.group(1)
    rule = rule.replace(p_old.group(0), p_old.group(0) + f'{ind_p}targets=config["targets_bed"],\n', 1)
    rule = rule.replace(l_old.group(0), l_old.group(0) +
                        f"{ind_l}-L {{params.targets}} \\\n{ind_l}--interval-set-rule INTERSECTION \\\n", 1)
    smk.write_text(s[:start] + rule + s[end:])
    changed.append("1a HaplotypeCaller -L targets_bed")

# ---- 1b: schema accepts targets_bed ------------------------------------------
sch = root / "workflow/schemas/config.schema.yaml"
t = sch.read_text()
if "targets_bed:" not in t:
    if "\nproperties:\n" not in t:
        die(f"{sch} is not in the expected form")
    t = t.replace("\nproperties:\n",
                  "\nproperties:\n  targets_bed:\n    type: string\n"
                  "    description: Path to BED of target regions; HaplotypeCaller is restricted to these.\n", 1)
    sch.write_text(t)
    changed.append("1b schema targets_bed")

# ---- 1c: intervals built from the target BED ---------------------------------
NEW_RULE = '''rule filter_picard_intervals:
    # CTS edit: chunks are cut from the target BED, not the whole genome
    input:
        **REF_FILES,
        targets=config["targets_bed"],
    output:
        intervals="results/intervals/filtered.interval_list",
    conda:
        "../envs/gatk.yaml"
    benchmark:
        "benchmarks/intervals_filter.txt"
    log:
        "logs/intervals_filter.txt",
    shell:
        """
        picard BedToIntervalList \\
            -Xmx{resources.mem_mb_reduced}m \\
            INPUT={input.targets} \\
            SEQUENCE_DICTIONARY={input.ref_dict} \\
            OUTPUT={output.intervals} \\
            SORT=true \\
            UNIQUE=true \\
            &> {log}
        """


'''
iv = root / "workflow/rules/intervals.smk"
u = iv.read_text()
if "CTS edit: chunks are cut from the target BED" not in u:
    a = u.find("rule filter_picard_intervals:")
    b = u.find("checkpoint create_gvcf_intervals:")
    if a == -1 or b == -1 or b < a:
        die(f"{iv} is not in the expected form")
    iv.write_text(u[:a] + NEW_RULE + u[b:])
    changed.append("1c intervals from targets_bed")

# ---- 1d: QC sample filter never returns an empty list -------------------------
qc = root / "workflow/modules/qc/Snakefile"
q = qc.read_text()
OLD = """            with open(samps_path, "w") as handle:
                for sample in passing:"""
NEW = """            if not passing:  # CTS edit: never hand PLINK an empty sample list
                passing = list(samples)
                with open(log_path, "a") as handle:
                    handle.write("No sample passed min_depth; keeping all VCF samples.\\n")
            with open(samps_path, "w") as handle:
                for sample in passing:"""
if "CTS edit: never hand PLINK an empty sample list" not in q:
    if q.count(OLD) != 1:
        die(f"{qc} is not in the expected form")
    qc.write_text(q.replace(OLD, NEW))
    changed.append("1d QC keeps all samples if none pass")

print("Applied: " + ", ".join(changed) if changed else "All CTS edits already present.")
