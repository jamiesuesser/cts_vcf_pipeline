# CTS VCF Pipeline

## What this pipeline does

This pipeline turns raw DNA sequencing reads from California tiger salamander
exon-capture samples into a **VCF file**, a table of genetic variants (SNPs and
small insertions/deletions) for every sample.

It is built on **snpArcher**, a published variant-calling workflow, with one key
change: reads are mapped against the whole axolotl reference genome, but
variants are only called inside the **targeted exon regions**.

The genome is ~32 billion bases, while the targets total about 31 million, so
calling only the targets saves a lot of time and avoids empty calls.

You fill in one settings file, run one command, and get:

- a VCF of all your samples, genotyped together
- a per-sample summary table: read quality, mapping rate, duplicates,
  sequencing depth on the targets, a pass/fail depth check, and your sample
  metadata, all linked by HBS number
- an email as each step finishes, saying whether any samples failed

---

## Before running you need the following:

See [`REQUIREMENTS.md`](REQUIREMENTS.md) for software and tested versions.

- Raw paired-end FASTQ files
	- File names must end in `_R1_001.fastq.gz` and `_R2_001.fastq.gz`
 	- HBS number first, e.g. `103980_S12_L001_R1_001.fastq.gz` 
- The snparcher conda environment (Snakemake 9.27.0, Python 3.11.4)
- Reference genome (FASTA) (The index is built automatically on the first run (~17 h) and reused after that)
- Target regions (bait BED) (The pipeline will automatically sort if needed) 
- Optional: metadata spreadsheet saved as `.csv` or `.tsv`, with a column of HBS numbers

---

## How to run

1. **Fill in the settings file:** `vcf_pipeline/edit_me_before_running.yaml`.
  
2. **Log in to tinkercliffs2** and run these from any folder:

   ```
   bash /projects/cts/jamie/vcf_pipeline/run_pipeline.sh --test-email   # check email works
   bash /projects/cts/jamie/vcf_pipeline/run_pipeline.sh --dry-run      # preview, runs nothing
   bash /projects/cts/jamie/vcf_pipeline/run_pipeline.sh                # real run
   ```

   In the dry-run list, `index_reference` only appears if no saved index
   exists yet for your reference (expected the first time only).

**To check on the run, run the followwing from any folder**:
   ```
   screen -r vcf_<run_name>                                   # watch live
   tail -f /projects/cts/jamie/runs/<run_name>/logs/pipeline_console.log   # or follow the log
   ```

---

## Where the run itself runs

`bash run_pipeline.sh` submits a small SLURM job (`ctl_<run_name>`: 2 cores,
8 GB, up to 7 days) that runs Snakemake, which then submits all the other jobs.
It does not run on the login node: ARC limits CPU use there, and Snakemake
managing ~1000 jobs used ~7.5 CPUs (ARC asked us to move it, 2026-11-11).
The log is still `<run folder>/logs/pipeline_console.log`. Stop a run with
`scancel` on the controller job, then `scancel -u $USER` for the jobs it started.

## Test run on a subset (e.g. 50 samples)

In `edit_me_before_running.yaml` set `run_name: "batch03_test50"` and
`test_subset_size: 50`, then dry-run and run as usual. The run uses 50 samples
spread evenly through the batch (listed in `config/test_subset_samples.txt`)
and goes through every step, including joint genotyping, the VCF and the QC
dashboard. Set `test_subset_size: 0` again for the full run.

## Checking resource use (memory / time)

After a run (or partway through), with the snparcher conda env active:
```
python /projects/cts/jamie/vcf_pipeline/scripts/resource_report.py /projects/cts/jamie/runs/<run_name>
```
It prints one row per step: peak memory vs. what was requested, run time, and
CPU use, flags steps outside 50-70% memory use, and writes
`resource_report.tsv` and `suggested_set_resources.yaml` in the run folder.
Copy the suggestions you agree with into `templates/profile.yaml`.

---

## What happens, step by step

### Getting ready (seconds to a few minutes) 

1. **Reads your settings** from `edit_me_before_running.yaml` and makes a run
   folder: `runs/<run_name>/`.

2. **Finds your samples.** It looks in your raw data folder(s), pairs each R1
   file with its R2 file, and uses the HBS number as the sample name. It skips
   "Undetermined" reads (reads that didn't match any sample barcode) and any
   samples you excluded.

3. **Links your metadata**, if you gave a spreadsheet, by matching HBS
   numbers.

4. **Checks the target regions.** Makes sure every region in the BED is on a
   chromosome that exists in the reference (stops with an error if not, which
   usually means the two files come from different genome versions), and
   sorts the regions into the same order as the reference.

5. **Writes the settings snpArcher needs** (sample list, reference, target
   regions, thresholds, cluster settings) into the run folder.

6. **Sets up the reference index.** An "index" is a lookup table that lets the
   mapper search the genome quickly. If one was already built for this
   reference, it is reused. If not, snpArcher builds it during the run (~17
   hours, once), and the pipeline saves it so later runs skip this.

### Processing the samples (hours to days; runs as many cluster jobs at once)

Each sample's mapping steps run together as **one** 16-core cluster job,
HaplotypeCaller for each sample is one small 1-core job, and each
joint-genotyping chunk is one job (see `SNParcher_changes.md` section 4).

7. **Cleaning the reads (fastp).** Removes leftover adapter sequence and
   low-quality bases from each read.
   *Email: Step 1/5 done.*

8. **Mapping the reads (BWA).** Works out where in the genome each read came
   from, and marks PCR duplicates (copies of the same original DNA fragment) so
   they aren't double-counted. Produces one BAM file per sample.
   *Email: Step 2/5 done.*

9. **Finding variants in each sample (GATK HaplotypeCaller).** Looks at each
   sample's reads in the target regions and records where it differs from the
   reference, over the target regions only (`hc_chunks_per_sample`, default 1
   chunk per sample).
   *Email: Step 3/5 done.*

10. **Combining all samples (GATK joint genotyping).** Merges every sample into
   one VCF and genotypes them together, so every sample is scored at the same
   sites, then flags low-quality variants. This produces the final VCF.
   *Email: Step 4/5 done, VCF ready.*

If a job fails (for example, it runs out of memory), it is retried
automatically with more memory. One failed sample does not stop the others.

### Checking sequencing depth (under an hour)

11. **Measures on-target depth.** For each sample, counts how many reads cover
   each target region, leaving out duplicates and poorly mapped reads.

12. **Writes the sample summary table**, one row per sample with quality
   stats, depth, a pass/fail against your minimum depth, and metadata.
   *Email: Step 5/5 done, pipeline finished.*

---

## Output files in `runs/<run_name>/`:
- `results/vcfs/` - **The final VCF(s)** 
- `results/qc_metrics/sample_summary.tsv` - One row per sample: HBS number, read/mapping/duplicate stats,
 on-target depth, % of target bases at the minimum depth or above, pass/fail, and all metadata columns
- `results/qc_metrics/low_depth_samples.txt` - Samples below the minimum depth
- `results/qc/qc_summary/` - VCF quality tables from bcftools: `vcf_qc_summary.txt` (samples, sites,
 SNPs, indels, % passing filters, Ts/Tv), `per_sample.tsv`, `sites.tsv.gz` (per-site QUAL/DP/QD/FS/MQ/SOR,
 missingness, MAF, FILTER), `filter_counts.txt`, `stats.txt`
- `results/bams/markdup/` - Mapped reads (BAM) per sample
- `logs/pipeline_console.log` - Everything printed during the run 
- `edit_me_used_for_this_run.yaml` - A copy of the exact settings used 

In the kept copy (`keep_results_root/<run_name>/`) things are grouped more simply:
- `pipeline_config/` - `config/`, `profile/`, `benchmarks/`, `edit_me_used_for_this_run.yaml`, `COPIED_FROM.txt`
- `logs/` - `pipeline_console.log` and every job's log
- `results/vcfs/` - the VCFs
- `results/qc/` - snpArcher's QC dashboard files, plus `qc_metrics/` (sample summary), `qc_summary/` (VCF QC)
  and `ontarget_depth/` (per-sample mosdepth output)
- `results/pipeline_outputs/` - intermediate outputs: `fastp/`, `gvcfs/`, `genomics_db/`, `intervals/`
- `logs/` - Detailed logs for every job (look here when something fails) 

---

## Where files go: working folder vs kept results

Set in `edit_me_before_running.yaml`:

- `output_root` - **working folder** for runs, e.g. `/scratch/<your PID>/runs`. Everything is made
  here, including the big files: BAMs (~4.5 GB per deep sample), the GenomicsDB workspace and a copy of
  the reference index. ARC's `/scratch` has no size limit, but **files untouched for 90 days are
  deleted automatically**.
- `keep_results_root` - **kept results**, e.g. `/projects/cts/<you>/runs`. When a run finishes, the
  VCFs, GVCFs, QC tables/dashboard, logs and settings are copied here (BAMs are not). Leave it `""`
  to keep everything in `output_root` instead.

If the copy fails (for example the project is full), nothing is deleted; fix it and run
`bash run_pipeline.sh --copy-results`. Use `scratchls` / `scratchrm` to see and clean the working folder.
Trimmed reads (`results/filtered_fastqs`) are deleted automatically once each sample is mapped.

---

## Helper commands for watching a run (fish shell)

Four shortcuts for the [fish shell](https://fishshell.com). Install once per user:

```fish
bash /path/to/vcf_pipeline/tools/fish/install.sh
```

This copies them to `~/.config/fish/functions/` and records your runs folder (from
`edit_me_before_running.yaml`) in `~/.config/fish/conf.d/cts_pipeline.fish`. Re-run it if you move
the pipeline or change `output_root`. Open a new terminal afterwards.

| Command | What it shows |
|---|---|
| `runstatus <run_name>` | Progress of each pipeline step (done / total, errors) and the VCFs made so far |
| `jobstatus <run_name>` | What each running cluster job is doing right now |
| `sqs` | Your SLURM queue, labeled with pipeline step and sample(s) |
| `checkrun <run_name>` | Full check after a run: finished?, VCF quality, sample QC, memory/time per step. Saves `run_check.txt` |
| `scratchls` | Runs in your working folder (`output_root`, e.g. `/scratch`): size, BAM size, days since last used, and whether results were copied out |
| `scratchrm <run>` | Deletes a run from the working folder after asking (`--bams-only` deletes just its BAMs). Refuses while the run is going and warns if its results were never copied |

The pipeline itself runs in bash, so fish is only needed for these shortcuts.

---

## Other commands you can add to `run_pipeline.sh`
-  `--dry-run` - Shows what would run, runs nothing
- `--test-email` - Sends one test email
- `--prepare-only` - Builds the run folder and settings, runs nothing
- `--depth-only` - Re-runs only the depth check and summary table 
- `--unlock` - Clears a leftover lock if a previous run was killed
- `--copy-results` - Only copies a finished run's results to `keep_results_root`
- `--vcf-qc-only` - Only (re)runs the VCF quality tables on a finished run

---

## What's in each folder/file:
- `edit_me_before_running.yaml` - **The only file you edit.** All settings and thresholds
- `run_pipeline.sh` - The command file you run to run the pipeline 
- `README.md` - This file
- `SNParcher_changes.md` - Exactly what we changed from the original snpArcher, and why
- `scripts/run_pipeline.py` - Does the work: builds the sample list and settings, runs snpArcher,
 then the depth summary 
- `scripts/ontarget_depth_array.sh` - Cluster job that measures on-target depth 
- `scripts/vcf_qc.sh` - Cluster job that makes the VCF quality tables (bcftools)
- `scripts/notify.py` - Sends the step emails 
- `scripts/setup_snparcher.sh` - One-time setup: downloads snpArcher and applies our edits
- `scripts/update_snparcher.sh` - Adds any newer edits to an existing `snpArcher/` folder
- `scripts/resource_report.py` - Memory/time use per step, with suggested settings
- `scripts/job_wrap.sh` - Runs every cluster job with Java's temp folder on the node's own scratch disk
 (some ARC nodes have a full `/tmp`, which made GATK crash)
- `tools/fish/` - The `sqs`, `runstatus`, `jobstatus` and `checkrun` commands, plus `install.sh`
- `tools/print_versions.sh` - Prints the software versions in use (for `REQUIREMENTS.md`)
- `REQUIREMENTS.md` - Software you need, and the versions this was tested with
- `templates/` - Base snpArcher settings and cluster settings 
- `reference/` - Reference genome, target regions, and `prepared/` (the saved index) 
- `snpArcher/` - snpArcher itself (git branch `targeted-calling`) 
- `conda_envs/` - Software environments, built automatically on the first run 

---

## Notes

- **HBS number** = the leading digits of the sample name (`104935R` becomes
  `104935`). It's how samples link to metadata.

- **Re-running:** a run only redoes steps whose input files have changed.
  If you change a threshold, use a new `run_name` (or delete the outputs you
  want redone).

- **Combining batches:** list several folders under `raw_fastq_dirs` to
  genotype them together in one VCF.

- **New reference or bait design:** just change `reference_fasta` and/or
  `targets_bed`. The pipeline notices the reference changed and builds a new
  index on the next run.

- **Moving the reference:** use `mv` or `cp -p`. A plain `cp` gives the file a
  new timestamp, which triggers a full ~17-hour re-index.
