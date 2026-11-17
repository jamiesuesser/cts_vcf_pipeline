# Changes to snpArcher for the CTS pipeline

What we changed or added relative to base snpArcher (harvardinformatics/snpArcher, v2), and why.

**Goal:** map reads to the whole axolotl genome, but call variants (GATK HaplotypeCaller) only in the
 exon-capture bait regions.

---

## 1. snpArcher code changes (4 files)

The only edits to snpArcher's own code. They live on git branch **`targeted-calling`** in `vcf_pipeline/snpArcher/`, on top of upstream snpArcher commit **`8a73e5b`**. `scripts/setup_snparcher.sh` downloads that version
 and applies these edits automatically (`scripts/patch_snparcher.py`). To add a newer edit to an existing
 `snpArcher/` folder, run `bash scripts/update_snparcher.sh` (safe to run more than once).

To see the exact diff:
```
cd /projects/cts/jamie/vcf_pipeline/snpArcher
git diff main targeted-calling
```

### 1a. `workflow/rules/variant_calling/gatk_intervals.smk`, rule `gatk_haplotypecaller_interval`

Added one parameter:
```python
    params:
        ploidy=config["variant_calling"]["ploidy"],
        min_pruning=1 if config["variant_calling"]["expected_coverage"] == "low" else 2,
        min_dangling=1 if config["variant_calling"]["expected_coverage"] == "low" else 4,
        targets=config["targets_bed"],                      # ADDED
```

Added two lines to the HaplotypeCaller command, right after `-L {input.interval} \`:
```
        -L {input.interval} \
        -L {params.targets} \                               # ADDED
        --interval-set-rule INTERSECTION \                  # ADDED
```

**Effect:** each HaplotypeCaller job calls only where snpArcher's interval overlaps the target BED.



### 1b. `workflow/schemas/config.schema.yaml`

Added a top-level property (next to `samples` and `sample_metadata`), because the schema rejects unknown config
 keys:
```yaml
  targets_bed:
    type: string
    description: Path to BED of target regions; HaplotypeCaller is restricted to these.
```

### 1c. `workflow/rules/intervals.smk`, rule `filter_picard_intervals` (added 2026-11-10)

snpArcher normally cuts the genome into chunks (`ScatterIntervalsByNs` over the whole ~32 Gb reference), then
splits those into HaplotypeCaller chunks and GenomicsDB (joint genotyping) chunks. The rule now builds that
interval list from the target BED instead:
```
picard BedToIntervalList INPUT={input.targets} SEQUENCE_DICTIONARY={input.ref_dict} \
    OUTPUT=results/intervals/filtered.interval_list SORT=true UNIQUE=true
```
**Effect:**
- Every HaplotypeCaller chunk contains targets, so no job can fail with "empty intersection" (before, a
  genome chunk with no baits failed for every sample, and with it every sample's gVCF and the VCF).
- Chunks are balanced by target bases, not genome bases, so they take similar time.
- Joint genotyping only runs over the targets. Before, it ran over the whole genome in
  0.15 x samples x 50 chunks (3,600 jobs for 480 samples, nearly all empty).
- The whole-genome `ScatterIntervalsByNs` step no longer runs.

Note: this only affects new run folders. An old run folder keeps its old `results/intervals/`.

### 1d. `workflow/modules/qc/Snakefile`, QC sample filter (added 2026-11-11)

The QC dashboard leaves out samples whose mean SNP depth is at or below `qc: min_depth`. If that
left no samples, PLINK got an empty VCF and the run ended with an error (happened in
batch03_test12, where every sample was below snpArcher's default of 2). Now, if no sample passes,
all samples are kept and the log says so. The cutoff itself is now `qc_min_sample_depth` in
`edit_me_before_running.yaml` (default 0).

### Not changed
Mapping (fastp, BWA, duplicate marking), GenomicsDBImport, GenotypeGVCFs, filtering, callable sites and the
 QC/postprocess modules are all stock.

---

## 2. Target BED preparation

 Source: `/projects/cts/backup/fromIRIS/fonmCTS/batch01/beds/Final_Design_baitCoverage300bpBuffer.bed`
 (bait design, 300 bp buffer)
 Used: `/projects/cts/jamie/reference/targets_sorted.bed` (39,908 targets, 31.0 Mb)
 Change: Sorted into the reference's contig order (`.fai` order), then by start

**Now automatic:** each run checks that every BED contig exists in the reference and writes a reference-sorted
 copy to `runs/<run_name>/config/targets_sorted.bed`, so any BED can be supplied.

**Why:** the original BED was not sorted. GATK's `INTERSECTION` needs both interval lists in the same order;
 unsorted, ~89% of HaplotypeCaller jobs failed with "empty intersection". Command used:

```
awk 'NR==FNR{o[$1]=NR; next} {print o[$1]"\t"$0}' results/reference/Axo.fa.gz.fai ORIGINAL.bed \
  | sort -k1,1n -k3,3n | cut -f2- > targets_sorted.bed
```

---

## 3. snpArcher config (`templates/config.yaml`), changes from the template

Settings changed:

```yaml
targets_bed: "reference/targets_sorted.bed"      # ADDED - used by the edit in 1a

reference:
  name: "Axo"                                    # CHANGED - AmbMex60DD split500mil reference,
  source: "reference/Axo_Ref.fna"                # CHANGED   same as the earlier lab pipeline

variant_calling:
  expected_coverage: "high"                      # CHANGED (was "low") - exon capture

callable_sites:
  coverage:
    fraction: 0.9                                # CHANGED (was 1.0) - one weak sample shouldn't drop sites for everyone
  mappability:
    enabled: false                               # CHANGED (was true) - GenMap is impractically slow on a ~32 Gb genome

modules:
  qc:
    enabled: false                               # optional - can be turned on in the settings file
  postprocess:
    enabled: false                               # optional - can be turned on in the settings file
```

For more details about these settings, see `edit_me_before_running.yaml`.

Each run, the pipeline fills in the sample list, reference (`reference_fasta`, `reference_name`, `targets_bed`) and thresholds from `edit_me_before_running.yaml`.

---

## 4. Execution profile (`templates/profile.yaml`)

Sized from the 12-sample test run `batch03_test12` (2026-11-10/11; numbers from
`resource_report.py` and `seff`).

```yaml
executor: slurm                                  # native SLURM plugin; bin/srun wrapper restores SLURM_CONF
slurm-efficiency-report: true
jobs: 100 / latency-wait: 60 / keep-going / rerun-incomplete / retries: 2
cores: 16                                        # max cores per SLURM job
groups:                                          # several steps share one SLURM job
  map: fastp ... bam_stats (1 sample per job)    # 16 cores, 78 GB
  hc:  HaplotypeCaller + gVCF merge (1 sample)   # 1 core, 2 GB
  jg:  GenomicsDBImport + GenotypeGVCFs (1 chunk)
default-resources: mem_mb attempt*2000, runtime attempt*240
```

| Step | Test run measurement | Setting now |
|---|---|---|
| mapping job (bwa) | 54-57 GB of 78 GB (69-71%); 35-50 min, 4.8 h for a 93M-read sample | 80 GB; bwa runtime 6 h (x attempt) |
| fastp / markdup | < 3.2 GB, < 7 min | 3 GB / 5 GB, 30 min |
| HaplotypeCaller | 16 chunks/sample grouped 4 samples per 16-core job: chunks ran one at a time, **5% CPU, 1% memory** used | 1 chunk per sample, its own 1-core 2 GB job |
| GenomicsDBImport | 3 GB peak, 2 min (12 samples) | 8 GB, grouped with genotyping |
| GenotypeGVCFs | 0.8 GB, 1 min (12 samples) | 6 GB |
| small steps | almost all < 1 GB, < 2 min | default 2 GB |
| whole-genome callable sites (mosdepth --d4, clam) | mosdepth 27 GB; clam ~3.5 h on 6 cores using 1 GB | **off** (`callable_sites_mask: false`) |

Joint-genotyping memory and time grow with sample count, so those requests have room above the
12-sample numbers; `attempt *` gives retries more.

Why groups instead of SLURM job arrays: arrays still schedule one task per step per sample and
the plugin holds a step until all its jobs are ready; arrays can't be combined with groups.

Re-check after each big run with `scripts/resource_report.py <run folder>`.

---

## 5. Added on top of snpArcher (not part of snpArcher)
- `edit_me_before_running.yaml` | All settings in one place: samples, reference files, thresholds, cluster, email |
- `scripts/setup_snparcher.sh` | One-time: downloads snpArcher `8a73e5b` and applies the section 1 edits |
- `scripts/patch_snparcher.py`, `scripts/update_snparcher.sh` | Apply the section 1 edits (new or existing checkout) |
- `scripts/resource_report.py` | Per-step memory/time use vs. requests, with suggested `set-resources` |
- `test_subset_size`, `hc_chunks_per_sample`, `joint_genotyping_chunks`, `callable_sites_mask`, `qc_min_sample_depth` | Settings for test runs, chunking, the callable-sites mask and the QC dashboard depth cutoff |
- `run_pipeline.sh` | Launcher; starts a screen session, activates conda |
- `scripts/run_pipeline.py` | Builds the sample sheet (v2 format, skips `Undetermined`), checks and sorts the
 target BED, reuses a saved reference index or saves a newly built one, writes config + profile, runs snpArcher |
- `scripts/ontarget_depth_array.sh` | mosdepth over `targets_sorted.bed` per sample (snpArcher's own depth is
 genome-wide, which reads ~0x for capture data) |
- `scripts/notify.py` | One email per finished step, flagging failed samples |
- Sample summary | `results/qc_metrics/sample_summary.tsv`: snpArcher QC + on-target depth + metadata linked by
 HBS number |

### 1e. Trimmed reads are temporary (`workflow/rules/fastq.smk`)
The `fastp` outputs in `results/filtered_fastqs/` are marked `temp()`, so Snakemake deletes them once
the sample is mapped. They are only read by `bwa_mem` and take ~3 GB per deep sample. Applied by
`scripts/patch_snparcher.py`; add it to an existing `snpArcher/` with `scripts/update_snparcher.sh`.
