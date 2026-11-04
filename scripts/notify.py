"""Email notifications for the CTS VCF pipeline.

Reads Snakemake's output as it runs and sends ONE email when each step has
finished for every sample, saying whether any sample failed in that step.

Steps:
  1. Read trimming (fastp)
  2. Mapping + duplicate marking (BAMs)
  3. Variant calling (HaplotypeCaller, per sample)
  4. Joint genotyping + filtering (sent when snpArcher exits)
  5. On-target depth + sample summary (sent by run_pipeline.py)
"""
import re
import shutil
import subprocess
import time
from collections import defaultdict

STAGES = [
    ("1/5 Read trimming (fastp)", re.compile(r"^fastp")),
    ("2/5 Mapping + duplicate marking", re.compile(r"bwa|merge_library_bams|markdup|merge_dedup|dedup")),
    ("3/5 Variant calling (HaplotypeCaller)", re.compile(r"haplotypecaller|concat_interval_gvcf|bcftools_call|deepvariant_call")),
]
OTHER = "4/5 Joint genotyping + filtering"


def stage_of(rule):
    for i, (_, pat) in enumerate(STAGES):
        if pat.search(rule):
            return i
    return None


# ------------------------------------------------------------------ sending
def send_email(s, subject, body):
    to = (s.get("notify_email") or "").strip()
    if not to:
        return False
    subject = f"[CTS {s['run_name']}] {subject}"
    try:
        for prog in ("mail", "mailx"):
            if shutil.which(prog):
                subprocess.run([prog, "-s", subject, to], input=body, text=True,
                               timeout=60, check=True)
                print(f"[vcf_pipeline] emailed: {subject}", flush=True)
                return True
        if shutil.which("sendmail"):
            msg = f"To: {to}\nSubject: {subject}\n\n{body}\n"
            subprocess.run(["sendmail", "-t"], input=msg, text=True, timeout=60, check=True)
            print(f"[vcf_pipeline] emailed: {subject}", flush=True)
            return True
        # Fallback: a 1-second SLURM job whose name is the subject (no body)
        subprocess.run(["sbatch", "-A", s["slurm_account"], "-p", s["slurm_partition"],
                        "-t", "1", "-J", subject[:120], "--mail-type=END",
                        f"--mail-user={to}", "-o", "/dev/null", "--wrap", "true"],
                       timeout=60, check=True, capture_output=True)
        print(f"[vcf_pipeline] emailed via SLURM (subject only): {subject}", flush=True)
        return True
    except Exception as e:  # never let email problems stop the pipeline
        print(f"[vcf_pipeline] WARNING: email failed ({e})", flush=True)
        return False


# ---------------------------------------------------------------- monitoring
class RunMonitor:
    RULE = re.compile(r"^(?:local)?rule (\S+):\s*$")
    ERROR = re.compile(r"^Error in rule (\S+):\s*$")
    FIELD = re.compile(r"^\s+(jobid|wildcards|log): (.*)$")
    FINISHED = re.compile(r"^Finished jobid: (\d+) \(Rule: (\S+)\)")
    RESTART = re.compile(r"Trying to restart job (\d+)")

    def __init__(self, s, run_dir, samples):
        self.s, self.run_dir, self.samples = s, run_dir, list(samples)
        self.jobs = {}                      # jobid -> (rule, sample)
        self.failed = {}                    # jobid -> (rule, sample, log)  final failures
        self.finished = set()
        self.seen = [False] * len(STAGES)   # stage had jobs this run
        self.emailed = [False] * len(STAGES)
        self.hc_done = defaultdict(int)     # sample -> finished HaplotypeCaller jobs
        self.block = None                   # current parse block
        self.last_check = time.time()

    # -- parsing
    def feed(self, line):
        line = line.rstrip("\n")
        m = self.RULE.match(line)
        if m:
            self.block = {"kind": "rule", "rule": m.group(1)}
            return self._tick()
        m = self.ERROR.match(line)
        if m:
            self.block = {"kind": "error", "rule": m.group(1)}
            return self._tick()
        m = self.FIELD.match(line)
        if m and self.block is not None:
            key, val = m.groups()
            self.block[key] = val.split(" (check")[0].strip()
            if key == "jobid" or ("jobid" in self.block and key in ("wildcards", "log")):
                self._commit()
            return self._tick()
        m = self.FINISHED.match(line)
        if m:
            jid, rule = int(m.group(1)), m.group(2)
            self.finished.add(jid)
            self.failed.pop(jid, None)
            sample = self.jobs.get(jid, (rule, None))[1]
            st = stage_of(rule)
            if st == 2 and "haplotypecaller" in rule and sample:
                self.hc_done[sample] += 1
            return self._tick()
        m = self.RESTART.search(line)
        if m:
            self.failed.pop(int(m.group(1)), None)
        return self._tick()

    def _commit(self):
        b = self.block
        jid = int(b["jobid"])
        rule = b["rule"]
        if b["kind"] == "rule":
            wc = dict(kv.split("=", 1) for kv in b.get("wildcards", "").split(", ") if "=" in kv)
            self.jobs[jid] = (rule, wc.get("sample"))
            st = stage_of(rule)
            if st is not None:
                self.seen[st] = True
        else:
            sample = self.jobs.get(jid, (rule, None))[1]
            self.failed[jid] = (rule, sample, b.get("log", ""))

    # -- stage completion
    def _tick(self):
        if time.time() - self.last_check > 60:
            self.last_check = time.time()
            self.check_stages()

    def failed_samples(self, stage):
        out = {}
        for rule, sample, log in self.failed.values():
            if stage_of(rule) == stage and sample:
                out.setdefault(sample, (rule, log))
        return out

    def _done(self, stage, sample):
        rd = self.run_dir / "results"
        if stage == 0:
            return any((rd / "fastp" / sample).glob("*/*.json"))
        if stage == 1:
            return (rd / "bams" / "markdup" / f"{sample}.bam").exists()
        n_int = len(list((rd / "intervals" / "gvcf").glob("*.interval_list")))
        return n_int > 0 and self.hc_done[sample] >= n_int

    def check_stages(self):
        upstream_failed = set()
        for i, (name, _) in enumerate(STAGES):
            fails = self.failed_samples(i)
            if not self.emailed[i] and self.seen[i]:
                pending = [x for x in self.samples
                           if x not in upstream_failed and x not in fails and not self._done(i, x)]
                if not pending:
                    self._email_stage(name, fails, upstream_failed)
                    self.emailed[i] = True
            upstream_failed |= set(fails)

    def _email_stage(self, name, fails, upstream_failed):
        n = len(self.samples) - len(upstream_failed)
        if fails:
            subject = f"Step {name}: done, {len(fails)} sample(s) FAILED"
        else:
            subject = f"Step {name}: done, all {n} samples OK"
        body = [f"Run folder: {self.run_dir}", f"Step: {name}",
                f"Samples in this step: {n}", f"Failed: {len(fails)}", ""]
        for sample, (rule, log) in sorted(fails.items()):
            body.append(f"  {sample}  (rule {rule})  log: {log}")
        if fails:
            body += ["", "Failed jobs were already retried. The run keeps going with the other samples."]
        send_email(self.s, subject, "\n".join(body))

    def finish(self, rc):
        """Called when snpArcher exits: email any unsent steps + step 4."""
        self.check_stages()
        for i, (name, _) in enumerate(STAGES):
            if self.seen[i] and not self.emailed[i]:
                fails = self.failed_samples(i)
                self._email_stage(name + " (ended early - see final email)" if rc else name,
                                  fails, set())
                self.emailed[i] = True
        other = sorted({(rule, sample or "-", log) for rule, sample, log in self.failed.values()
                        if stage_of(rule) is None})
        vcfs = sorted((self.run_dir / "results" / "vcfs").glob("*.vcf.gz"))
        ok = rc == 0
        subject = f"Step {OTHER}: " + ("done, VCF ready" if ok else "FAILED or incomplete")
        body = [f"Run folder: {self.run_dir}", f"snpArcher exit code: {rc}", ""]
        body += [f"VCF: {v}" for v in vcfs] or ["No VCF produced."]
        if other:
            body += ["", "Failed jobs in other steps:"]
            body += [f"  {r}  sample {s_}  log: {l}" for r, s_, l in other]
        body += ["", "Full log: pipeline_console.log in the run folder.",
                 "Step 5/5 (depth summary) runs next."]
        send_email(self.s, subject, "\n".join(body))
