#!/bin/bash
# Downloads snpArcher into vcf_pipeline/snpArcher and applies the CTS edits
# (see SNParcher_changes.md section 1) on git branch "targeted-calling".
# Run once:  bash /projects/cts/jamie/vcf_pipeline/scripts/setup_snparcher.sh
set -euo pipefail

PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PIPE/snpArcher"
COMMIT="8a73e5b"   # snpArcher version these edits were tested on

if [ -e "$DEST" ]; then
    echo "ERROR: $DEST already exists. Remove it first if you want a fresh copy."
    exit 1
fi

git clone https://github.com/harvardinformatics/snpArcher.git "$DEST"
cd "$DEST"
git checkout -q -b targeted-calling "$COMMIT"

python3 - <<'EOF'
import re, sys

smk = "workflow/rules/variant_calling/gatk_intervals.smk"
s = open(smk).read()
start = s.index("rule gatk_haplotypecaller_interval:")
end = s.find("\nrule ", start + 1)
end = len(s) if end == -1 else end
rule = s[start:end]

p_old = re.search(r"^(\s+)min_dangling=.*,\n", rule, re.M)
l_old = re.search(r"^(\s+)-L \{input\.interval\} \\\n", rule, re.M)
if not p_old or not l_old or "params.targets" in rule:
    sys.exit("ERROR: gatk_intervals.smk is not in the expected form - edit it by hand (see SNParcher_changes.md)")
ind_p, ind_l = p_old.group(1), l_old.group(1)
rule = rule.replace(p_old.group(0), p_old.group(0) + f'{ind_p}targets=config["targets_bed"],\n', 1)
rule = rule.replace(l_old.group(0), l_old.group(0) +
                    f"{ind_l}-L {{params.targets}} \\\n{ind_l}--interval-set-rule INTERSECTION \\\n", 1)
open(smk, "w").write(s[:start] + rule + s[end:])

sch = "workflow/schemas/config.schema.yaml"
t = open(sch).read()
if "\nproperties:\n" not in t or "targets_bed:" in t:
    sys.exit("ERROR: config.schema.yaml is not in the expected form - edit it by hand")
t = t.replace("\nproperties:\n",
              "\nproperties:\n  targets_bed:\n    type: string\n"
              "    description: Path to BED of target regions; HaplotypeCaller is restricted to these.\n", 1)
open(sch, "w").write(t)
print("Edits applied.")
EOF

git -c user.name="CTS pipeline" -c user.email="cts@localhost" commit -qam \
    "Restrict HaplotypeCaller to target BED (targets_bed + interval intersection)"
echo
git log --oneline -2
echo
git diff --stat HEAD~1
echo
echo "snpArcher ready at $DEST (branch targeted-calling)."
