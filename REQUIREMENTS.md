# Requirements

## Computing
- A Linux cluster with **SLURM** (`sbatch`, `squeue`, `sacct`, `scancel`; `seff` is optional, used by `checkrun`).
  Developed and tested on Virginia Tech ARC **Tinkercliffs** (`normal_q`).
- An account/allocation to charge jobs to (`slurm_account` in `edit_me_before_running.yaml`).
- Node-local scratch for job temp files. On ARC each job gets `/localscratch/<jobid>` as `$TMPDIR`;
  `scripts/job_wrap.sh` points Java/GATK there. On another cluster, check what `$TMPDIR` is inside a job.
- Disk: the axolotl reference alone is ~29 GB, and its index (built once, then reused) adds a
  similar amount. Per-sample BAMs and GVCFs come on top; check a test run to size a full batch.

## Software you install yourself
| Software | Needed for | Notes |
|---|---|---|
| **conda** (Miniforge/Mamba recommended) | creating the pipeline environment | snpArcher then builds its own tool environments in `conda_envs/` on the first run |
| **Python 3.11** + **Snakemake 9.27** | running snpArcher | in one conda env; its path goes in `snparcher_conda_env` |
| **snakemake-executor-plugin-cluster-generic** | submitting jobs to SLURM | `pip install snakemake-executor-plugin-cluster-generic` inside that env. The native SLURM plugin is **not** used (it could not submit jobs from inside the controller job on ARC) |
| **PyYAML** | `run_pipeline.py` | normally comes with Snakemake |
| **git** | `scripts/setup_snparcher.sh` | downloads snpArcher at commit `8a73e5b` and applies the CTS edits |
| **fish shell 3.x** (optional) | the `sqs` / `runstatus` / `jobstatus` / `checkrun` shortcuts | see `tools/fish/install.sh`; the pipeline itself runs in bash |

Example setup:
```bash
conda create -p /path/to/conda_env/snparcher -c conda-forge -c bioconda python=3.11 snakemake=9.27 pyyaml
conda run -p /path/to/conda_env/snparcher pip install snakemake-executor-plugin-cluster-generic
bash /path/to/vcf_pipeline/scripts/setup_snparcher.sh
```

## Installed automatically
GATK, BWA, samtools, bcftools, fastp, mosdepth, Picard, PLINK, ADMIXTURE and the other tools are
installed by snpArcher into `conda_envs/` the first time you run. You do not install them.

## Tested versions
The table below is produced by `bash tools/print_versions.sh` (re-run and append it after upgrading anything).

### Versions recorded on 2026-11-17 (tinkercliffs2)

| Software | Version |
|---|---|
| fish shell | not found |
| conda | conda 25.11.1 |
| SLURM | slurm 25.11.6 |
| Python (pipeline env) | Python 3.11.4 |
| Snakemake (pipeline env) | 9.27.0 |
| snakemake-executor-plugin-cluster-generic | 1.0.9 |
| snpArcher (git commit) | ee7a0c5 (2026-11-11) on branch HEAD -> targeted-calling |
| gatk4 | 4.6.2.0 |
| bwa | 0.7.19 |
| samtools | 1.25 |
| bcftools | 1.23,1.25 |
| htslib | 1.24,1.25 |
| picard | 3.5.0 |
| fastp | 1.4.0 |
| mosdepth | 0.3.3 |
| sambamba | 1.0.1 |
| plink | 1.90 |
| plink2 | 2.0.0a7.post13 |
| vcftools | 0.1.16 |
| admixture | 1.3.0 |
