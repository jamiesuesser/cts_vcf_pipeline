# How snpArcher was changed to use the target BED, explained simply

By default, snpArcher looks for variants across the whole ~32 billion-base
axolotl genome. Our samples are exon capture, so we only sequenced about 31
million bases of target regions (listed in the bait BED file). These changes
make snpArcher look for variants **only inside those target regions**, while
still mapping reads against the whole genome.

Three files were changed.

---

## 1. The rule that runs HaplotypeCaller

**File:** `snpArcher/workflow/rules/variant_calling/gatk_intervals.smk`
(rule `gatk_haplotypecaller_interval`)

snpArcher already gives HaplotypeCaller one region to work on, its own chunk
of the genome:

```
-L {input.interval}
```

We added a second region (our BED file) and told GATK to only work where the
two overlap:

```
-L {params.targets}
--interval-set-rule INTERSECTION
```

For that to work, the rule needs to know where the BED file is, so we added
one line to its settings that reads the BED path from the config file:

```python
targets=config["targets_bed"],
```

## 2. snpArcher's list of allowed settings

**File:** `snpArcher/workflow/schemas/config.schema.yaml`

snpArcher checks its config file and rejects any setting it doesn't recognize,
so we added `targets_bed` to its list of allowed settings:

```yaml
targets_bed:
  type: string
```

## 3. The config file

**File:** the snpArcher config (filled in automatically from
`edit_me_before_running.yaml` each run)

This gives snpArcher the path to the BED file:

```yaml
targets_bed: "/projects/cts/jamie/reference/targets_sorted.bed"
```

---

## How the pieces fit together

1. The **config file** says where the BED file is.
2. The **schema** lets snpArcher accept that new setting.
3. The **HaplotypeCaller rule** passes the BED to GATK and says "only call
   variants where snpArcher's chunk and the BED overlap."

## One extra requirement: the BED must be sorted

GATK reads the genome chunk and the BED side by side, in genome order. If the
BED's regions are out of order, GATK can't line them up and reports an "empty
intersection" error. The original bait BED was out of order, so it had to be
sorted to match the reference genome. The pipeline now does this
automatically every run.

For the exact line-by-line changes and settings, see `SNParcher_changes.md`.
