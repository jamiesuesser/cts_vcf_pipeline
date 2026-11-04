# Changes to snpArcher for the CTS pipeline

What we changed or added relative to base snpArcher (harvardinformatics/snpArcher, v2), and why.

**Goal:** map reads to the whole axolotl genome, but call variants (GATK HaplotypeCaller) only in the
 exon-capture bait regions.

---

## 1. snpArcher code changes (2 files)

The only edits to snpArcher's own code. They live on git branch **`targeted-calling`** in `vcf_pipeline/snpArcher/`, on top of upstream snpArcher commit **`8a73e5b`**. `scripts/setup_snparcher.sh` downloads that version
 and applies these edits automatically.

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

### Not changed
Mapping (fastp, BWA, duplicate marking), GenomicsDBImport, GenotypeGVCFs, filtering, callable sites and the
 QC/postprocess modules are all stock. Joint genotyping is faster because the gVCFs only contain target regions.

---

## 2. Target BED preparation

 Source: `/projects/cts/backup/fromIRIS/fonmCTS/batch01/beds/Final_Design_baitCoverage300bpBuffer.bed`
 (bait design, 300 bp buffer)
 Used: `vcf_pipeline/reference/targets_sorted.bed` (39,908 targets, 31.0 Mb)
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

**Settings changed:**
- `targets_bed` (new) | `reference/targets_sorted.bed` | Used by the edit in 1a |
- `reference.name` / `source` | `Axo` / `reference/Axo_Ref.fna` | AmbMex60DD split500mil reference, same as the
 earlier pipeline |
- `variant_calling.expected_coverage` | `high` | Exon capture |
- `callable_sites.coverage.fraction` | `0.9` (was 1.0) | One weak sample shouldn't drop sites for everyone |
- `callable_sites.mappability.enabled` | `false` (was true) | GenMap is impractically slow on a ~32 Gb genome |
- `modules.qc` / `postprocess` | `false` | Optional; can be turned on in the settings file |

For more details about these changes view the edit_me_before_running.yaml

Each run, the pipeline fills in the sample list, reference (`reference_fasta`, `reference_name`, `targets_bed`)
and thresholds from `edit_me_before_running.yaml`.

---

## 4. Execution profile (`templates/profile.yaml`), changes from snpArcher's default profile

**Settings changed:**
- `executor` | `cluster-generic` with an `sbatch` submit command | snpArcher's SLURM plugin strips `SLURM_CONF`
 from jobs, so `srun` failed on ARC |
- `default-resources` | `slurm_account: consgen`, `slurm_partition: normal_q`, `runtime: 720` | ARC allocation |
- `keep-going` / `rerun-incomplete` | `true` | One failed sample doesn't stop the run; interrupted outputs are
 redone |
- `retries` | `2` | Failed jobs retry with 2x then 3x memory (`attempt * ...`) |
- `index_reference` | 150 GB, 72 h | ~32 Gb genome; indexing took ~17 h |
- `bwa_mem` | `attempt * 80000` MB, 48 h | BWA index of this genome needs ~60+ GB |
- `create_db_intervals` | `attempt * 32000` MB | Ran out of memory at 8 GB with 480 samples |
- `conda-prefix` | `vcf_pipeline/conda_envs` | Tool environments shared across runs |
- `rerun-triggers` | `mtime` | Lets each run reuse the saved reference index |

Environment change: installed `snakemake-executor-plugin-cluster-generic` in the snparcher conda env.

---

## 5. Added on top of snpArcher (not part of snpArcher)
- `edit_me_before_running.yaml` | All settings in one place: samples, reference files, thresholds, cluster, email |
- `scripts/setup_snparcher.sh` | One-time: downloads snpArcher `8a73e5b` and applies the section 1 edits |
- `run_pipeline.sh` | Launcher; starts a screen session, activates conda |
- `scripts/run_pipeline.py` | Builds the sample sheet (v2 format, skips `Undetermined`), checks and sorts the
 target BED, reuses a saved reference index or saves a newly built one, writes config + profile, runs snpArcher |
- `scripts/ontarget_depth_array.sh` | mosdepth over `targets_sorted.bed` per sample (snpArcher's own depth is
 genome-wide, which reads ~0x for capture data) |
- `scripts/notify.py` | One email per finished step, flagging failed samples |
- Sample summary | `results/qc_metrics/sample_summary.tsv`: snpArcher QC + on-target depth + metadata linked by
 HBS number |
