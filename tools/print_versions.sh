#!/bin/bash
# Prints the software versions this pipeline is using, as a Markdown table.
#   bash <pipeline folder>/tools/print_versions.sh                 # show
#   bash <pipeline folder>/tools/print_versions.sh >> REQUIREMENTS.md   # record
PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$PIPE/edit_me_before_running.yaml"
ENV="$(grep -E '^snparcher_conda_env:' "$SETTINGS" | head -1 | sed -E 's/^[^:]+:[[:space:]]*//; s/[[:space:]]+#.*$//; s/"//g')"

row() { printf '| %s | %s |\n' "$1" "${2:-not found}"; }
first() { head -1 | tr -d '\r'; }

echo
echo "### Versions recorded on $(date +%Y-%m-%d) ($(hostname -s))"
echo
echo "| Software | Version |"
echo "|---|---|"
row "fish shell"  "$(fish --version 2>/dev/null | first)"
row "conda"       "$(conda --version 2>/dev/null | first)"
row "SLURM"       "$(sbatch --version 2>/dev/null | first)"
row "Python (pipeline env)"    "$("$ENV/bin/python" --version 2>/dev/null | first)"
row "Snakemake (pipeline env)" "$("$ENV/bin/snakemake" --version 2>/dev/null | first)"
row "snakemake-executor-plugin-cluster-generic" \
    "$("$ENV/bin/python" -m pip show snakemake-executor-plugin-cluster-generic 2>/dev/null | sed -n 's/^Version: //p')"
row "snpArcher (git commit)" "$(git -C "$PIPE/snpArcher" log -1 --format='%h (%cs) on branch %D' 2>/dev/null | first)"
row "this pipeline (git commit)" "$(git -C "$PIPE" log -1 --format='%h (%cs)' 2>/dev/null | first)"
# Tools inside the conda environments snpArcher created (read from conda metadata, nothing is run)
for t in gatk4 bwa bwa-mem2 samtools bcftools htslib picard fastp mosdepth sambamba plink plink2 vcftools admixture; do
    v="$(ls "$PIPE"/conda_envs/*/conda-meta/ 2>/dev/null | grep -E "^$t-[0-9]" | sed -E "s/^$t-([^-]+)-.*/\1/" | sort -uV | paste -sd, -)"
    if [ -n "$v" ]; then row "$t" "$v"; fi
done
