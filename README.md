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
   tail -f /projects/cts/jamie/runs/<run_name>/pipeline_console.log   # or follow the log
   ```

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

7. **Cleaning the reads (fastp).** Removes leftover adapter sequence and
   low-quality bases from each read.
   *Email: Step 1/5 done.*

8. **Mapping the reads (BWA).** Works out where in the genome each read came
   from, and marks PCR duplicates (copies of the same original DNA fragment) so
   they aren't double-counted. Produces one BAM file per sample.
   *Email: Step 2/5 done.*

9. **Finding variants in each sample (GATK HaplotypeCaller).** Looks at each
   sample's reads in the target regions and records where it differs from the
   reference. To run in parallel, the genome is split into ~50 chunks.
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
- `results/bams/markdup/` - Mapped reads (BAM) per sample
- `pipeline_console.log` - Everything printed during the run 
- `edit_me_used_for_this_run.yaml` - A copy of the exact settings used 
- `logs/` - Detailed logs for every job (look here when something fails) 

---

## Other commands you can add to `run_pipeline.sh`
-  `--dry-run` - Shows what would run, runs nothing
- `--test-email` - Sends one test email
- `--prepare-only` - Builds the run folder and settings, runs nothing
- `--depth-only` - Re-runs only the depth check and summary table 
- `--unlock` - Clears a leftover lock if a previous run was killed

---

## What's in each folder/file:
- `edit_me_before_running.yaml` - **The only file you edit.** All settings and thresholds
- `run_pipeline.sh` - The command file you run to run the pipeline 
- `README.md` - This file
- `SNParcher_changes.md` - Exactly what we changed from the original snpArcher, and why
- `scripts/run_pipeline.py` - Does the work: builds the sample list and settings, runs snpArcher,
 then the depth summary 
- `scripts/ontarget_depth_array.sh` - Cluster job that measures on-target depth 
- `scripts/notify.py` - Sends the step emails 
- `scripts/setup_snparcher.sh` - One-time setup: downloads snpArcher and applies our edits
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
