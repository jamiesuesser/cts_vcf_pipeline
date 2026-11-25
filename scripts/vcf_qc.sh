#!/bin/bash
# VCF quality stats (one SLURM job). Submitted by run_pipeline.py after the run finishes.
# Args: VCF OUT_DIR BCFTOOLS_BIN
# Outputs (in OUT_DIR):
#   stats.txt            full `bcftools stats -s -` report
#   summary_numbers.tsv  overall counts (samples, records, SNPs, indels, ...)
#   tstv.tsv             Ts/Tv
#   per_sample.tsv       per sample: hom-ref, hom-alt, het, Ts, Tv, indels, mean depth, ..., missing
#   sites.tsv.gz         per site: CHROM POS TYPE QUAL DP QD FS MQ SOR F_MISSING MAF FILTER
#                        (passing sites are written as PASS; snpArcher leaves them as ".")
#   filter_counts.txt    number of sites per FILTER value
#   n_samples.txt        number of samples
#SBATCH -t 8:00:00
#SBATCH -c 4
#SBATCH --mem=16G
set -euo pipefail

VCF=$1; OUT=$2; BCFTOOLS=$3
mkdir -p "$OUT"

# bcftools plugins (+fill-tags) live next to the binary in conda installs
export BCFTOOLS_PLUGINS="${BCFTOOLS_PLUGINS:-$(dirname "$BCFTOOLS")/../libexec/bcftools}"

"$BCFTOOLS" stats -s - --threads 4 "$VCF" > "$OUT/stats.txt"
grep '^SN'   "$OUT/stats.txt" | cut -f3- > "$OUT/summary_numbers.tsv"
grep '^TSTV' "$OUT/stats.txt" | cut -f3- > "$OUT/tstv.tsv"
grep '^PSC'  "$OUT/stats.txt" | cut -f3- > "$OUT/per_sample.tsv"

"$BCFTOOLS" +fill-tags "$VCF" -- -t F_MISSING,MAF \
  | "$BCFTOOLS" query -f '%CHROM\t%POS\t%TYPE\t%QUAL\t%INFO/DP\t%INFO/QD\t%INFO/FS\t%INFO/MQ\t%INFO/SOR\t%INFO/F_MISSING\t%INFO/MAF\t%FILTER\n' \
  | awk 'BEGIN{FS=OFS="\t"} $12=="." {$12="PASS"} {print}' \
  | gzip > "$OUT/sites.tsv.gz"

"$BCFTOOLS" query -l "$VCF" | wc -l > "$OUT/n_samples.txt"
zcat "$OUT/sites.tsv.gz" | cut -f12 | sort | uniq -c | sort -k1,1nr > "$OUT/filter_counts.txt"

echo "done: $OUT"
