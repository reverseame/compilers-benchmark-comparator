# Compilers Benchmark Comparator

This repository contains a pipeline that produces comparative measurements of
performance and security hardening across modern compilers — specifically
g++, clang++ and rustc. It originated as a Bachelor's thesis (TFG) presented
at EINA, University of Zaragoza, and now drives the measurement campaign of
the accompanying research article.

## Contents

- **scripts/campaign.py**: measurement campaign driver (CSV output). This is
  what produces the data used in the article — see "Measurement campaign"
  below.
- **scripts/measure_exec.c**: minimal fork/execv/wait4 wrapper used to time
  each benchmark execution and read its resource usage without inheriting
  the Python driver's memory footprint.
- **scripts/analyze.py**: turns a campaign's CSVs into the article's LaTeX
  tables and a data-quality summary.
- **scripts/plot_results.py**: turns a campaign's CSVs into the article's
  figures (PDF), with medians and 95% bootstrap confidence intervals.
- **scripts/paired_stats.py**: sweep-paired bootstrap, simultaneous
  (Bonferroni) bound, A/A control on byte-identical binaries, and baseline
  ELF properties — see "Post-processing".
- **scripts/build_cost.py**: isolated, repeated measurement of compilation
  cost (serial builds, several repetitions per cell) — see "Compilation
  cost".
- **scripts/rapl_window_check.c**: instrumented copy of the published
  `measure_exec.c` that measures how far the RAPL window extends beyond the
  wall-clock window — see "Energy window".
- **scripts/smt_stalls.sh**, **scripts/smt_stalls.py** and
  **scripts/count_events.c**: store-buffer stall counters with the
  measurement core's SMT sibling offline and online — see "SMT state and
  store-buffer stalls".
- **config/matrix.yaml**: the experimental matrix (compilers × optimization
  levels × security flags × programs). Single source of truth for the
  campaign.
- **programs**: benchmark source programs. Each benchmark exists as a
  functionally analogous `.cpp`/`.rs` pair (same algorithm and output; the
  libraries used and the safety semantics differ, e.g. `copy` calls glibc's
  `strcpy`/`strlen` in C++ while the Rust search is inlined).
- **Dockerfile.measure** and **docker-compose.yml**: lean container image for
  running the campaign on a server.

## Measurement campaign (v2, CSV output)

The measurement campaign runs through `scripts/campaign.py`:

- The experimental matrix is defined in **`config/matrix.yaml`**; adding a
  compiler or a flag requires no code changes.
- Compilations run concurrently (a thread pool), but **timed executions
  are strictly sequential** and sweep-major (one full pass over all binaries
  per repetition, so slow drift affects all cells equally).
- Within each sweep the cells run in a fixed order by default (as in the
  article's campaign). `--order rotate` shifts the starting cell evenly
  across sweeps; `--order random` shuffles the cells in every sweep (seeded
  with `--seed`). Each row of `runs.csv` records its `position` within the
  sweep, so run-order effects can be estimated (see `paired_stats.py`).
  `rotate` changes a cell's absolute position but keeps its neighbors;
  only `random` also breaks neighbor effects.
- Every execution is recorded **individually** in `runs.csv` (no
  aggregation): wall-clock time (`CLOCK_MONOTONIC`), user/system CPU time,
  peak RSS, page faults, context switches and **exit status** — all from the
  same execution, via `wait4(2)`. A warmup sweep is recorded flagged with
  `is_warmup=1`.
- When the host allows it, each execution also records **hardware counters**
  (instructions, cycles, branch misses, cache misses; user space only,
  attached before `exec` so process startup is included) and **RAPL energy
  deltas** (package and core domains). Both degrade gracefully to empty CSV
  cells when unavailable. In practice, under Docker on Debian they need:
  - counters: `sudo sysctl kernel.perf_event_paranoid=1` on the host
    (Debian patches the kernel with a level 3 that blocks `perf_event_open`
    even with `--cap-add PERFMON`; restore the original value afterwards)
    plus `--security-opt apparmor=unconfined`;
  - energy: `sudo modprobe intel_rapl_msr` on the host and a bind mount of
    the powercap tree at `/rapl`,
    `-v /sys/devices/virtual/powercap:/rapl:ro`, because the container's
    sysfs lists `/sys/class/powercap` entries without materializing their
    targets (and bind mounts under `/sys` do not take effect either); the
    wrapper checks `/rapl` as a fallback. RAPL counts the whole package,
    not just the pinned core.
  Check `environment.txt` (`perf_event_paranoid`, `rapl_energy`) to confirm
  both were active during a campaign.
- Compilation cost is recorded per binary in `binaries.csv`
  (`compile_wall_s`, `compile_user_s`, `compile_sys_s`,
  `compile_max_rss_kb`). Compilations run concurrently in a thread pool of
  `os.cpu_count()` workers; when the container is pinned to a single CPU
  they time-share that CPU, so wall time includes waiting for it and user+sys
  is the more robust figure. Each cell is compiled once, so these figures
  are descriptive; `scripts/build_cost.py` provides a repeated measurement.
- The corpus includes a `startup` benchmark (minimal program) that
  measures exec-to-exit time: the clock starts after `fork`, just before
  `execv`, and stops when `wait4` returns, so it covers exec, dynamic
  loading, initialization, output and termination but not `fork`. This is
  where PIE and full RELRO
  (`-z now`, eager binding) pay their real cost; the loop benchmarks
  amortize it away.
- If a binary does not exit 0 with the expected output, the row is flagged
  (`output_ok=0`) and the campaign warns at the end: a crashing execution can
  never masquerade as a valid measurement.
- Per-binary properties go to `binaries.csv`: exact compiler invocation,
  size (as produced and stripped), checksec fields (RELRO, canary, NX, PIE,
  fortified/fortifiable counts) and sha256.
- The execution environment is captured in `environment.txt`: CPU, kernel,
  governor, turbo state, glibc, exact compiler versions, cgroup limits and
  CPU affinity. The matrix used is copied next to the results.

### Running on a server

This is the configuration of the article's campaign (Intel Core i7-6700,
4 cores / 8 threads, measurement on CPU 3, whose SMT sibling is CPU 7). To
repeat the published campaign exactly, use the image pinned by digest (see
"Reproducing the article") instead of building one.

```sh
# 1. Prepare the host (outside the container):
sudo cpupower frequency-set -g performance      # governor
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo  # turbo off
echo 0 | sudo tee /sys/devices/system/cpu/cpu7/online  # sibling of CPU 3 offline

# 2. Build the lean image (GCC 14.2 / Clang 19 from Debian trixie). The
#    default toolchain, nightly-2026-06-30, installs the article's
#    rustc 1.98.0-nightly (096694416 2026-06-29):
docker build -f Dockerfile.measure \
  --build-arg RUST_TOOLCHAIN=nightly-2026-06-30 \
  -t compiler-benchmark-measure .

# 3. Optional, for hardware counters and RAPL energy (see the metrics
#    section above; restore afterwards):
sudo sysctl kernel.perf_event_paranoid=1
sudo modprobe intel_rapl_msr

# 4. Launch the campaign pinned to the single measurement core, with no
#    CPU limits:
docker run --rm --cpuset-cpus=3 --cap-add PERFMON \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -v /sys/devices/virtual/powercap:/rapl:ro \
  -v "$PWD/results_csv:/app/results_csv" \
  compiler-benchmark-measure --reps 50 --keep-binaries

# 5. Restore the host afterwards:
echo 1 | sudo tee /sys/devices/system/cpu/cpu7/online
```

On another CPU, pick the measurement core and its sibling from
`/sys/devices/system/cpu/cpu<N>/topology/thread_siblings_list`.

Useful options: `--programs suma,final`, `--compilers g++,clang++,rustc`,
`--reps N`, `--order random --seed N`, `--keep-binaries` (keeps the
compiled binaries next to the CSVs so they can be archived as an artifact).

Results are written to
`results_csv/<timestamp>/{runs.csv,binaries.csv,environment.txt,matrix.yaml}`.

**Warning — SMT state changes more than noise.** On benchmarks with a
store-heavy hot loop (e.g. a `strcpy` loop inside libc) we measured
**~2.8x** runtime differences between otherwise identical campaigns
depending solely on whether the pinned core's sibling was online, with
byte-identical binaries and glibc's `ld.so --list-diagnostics` output
identical in both states. The sign of `_FORTIFY_SOURCE`'s effect on `copy`
flips with it, and the magnitude of other cells changes too (Clang's ASan
on `copy`: 2.94x offline, 3.97x online). The mechanism is unknown: the
store-buffer hypothesis we first proposed was refuted by stall counters (see
"SMT state and store-buffer stalls"). Pick one SMT state, keep it for every
campaign you intend to compare, and check it is recorded in
`environment.txt` (`smt_control` / `cpus_online`; with per-CPU hotplug,
`smt_control` stays `on` and `cpus_online` reads `0-6`).

### How many repetitions?

The article's matrix has 1,017 cells, of which 999 compile (Rustc cannot
build its MSan cells). One sweep over the 999 binaries took about 6.3
minutes on the reference server, so a campaign takes roughly
`6.3 min × (reps + 1)`; the article's 50 repetitions took 5.3 hours.

| `--reps` | duration | note |
|---------:|---------:|------|
| 10       | ~1.2 h   | enough for smoke tests |
| 50       | ~5.3 h   | the article's campaign |
| 100      | ~10.6 h  | diminishing returns |

The median coefficient of variation is 0.8% on the loop benchmarks and
3.2% on `startup`, so the confidence interval of the median shrinks below
any effect of interest well before 100 repetitions. Statistics are computed
downstream from the raw rows, so the choice of `--reps` never changes the
analysis code.

## Post-processing

Both tools read a results directory and are pure Python (matplotlib is the
only third-party dependency, needed for the figures only):

```sh
pip3 install -r requirements.txt   # matplotlib

# LaTeX tables + data-quality summary  ->  results_csv/<ts>/tables/
python3 scripts/analyze.py results_csv/<timestamp>

# Figures (PDF) + per-cell statistics  ->  results_csv/<ts>/figures/
python3 scripts/plot_results.py results_csv/<timestamp>
```

`plot_results.py` reports the **median** of the timed repetitions with a 95%
percentile **bootstrap confidence interval** (bands on line plots, whiskers
on bar plots) rather than plain means: the median is robust to the
occasional interference outlier, and the CI makes it visible when two
configurations are statistically indistinguishable. It also writes
`figures/cell_stats.csv` with the median and CI of every cell (time and
RSS), which is the numeric source behind every figure.

### Paired statistics and A/A control

`paired_stats.py` re-analyzes `runs.csv` and `binaries.csv` (standard library
only; about 100 s on the campaign host, an i7-6700 with Python 3.11, for the
definitive campaign); it does not need the container:

```sh
python3 scripts/paired_stats.py results_csv/20260720-114151-definitive
```

It resamples each flag cell and its baseline together by sweep (5000
resamples, seed 20260708), computes a Bonferroni simultaneous bound over the
classical-defense cells whose binary differs from the baseline, and uses the
cells that are byte-identical to their baseline (same SHA-256) as an A/A
control. It writes `tables/paired_stats.txt` and `tables/paired_cells.csv`;
run `plot_results.py` first, because the A/A control also reads
`figures/cell_stats.csv`.

For a campaign run with `--order rotate` or `--order random`, it also
reports the run-order effect: the median deviation of each execution from
its cell's median, by position decile within the sweep. With a random order,
the A/A control no longer confounds a cell's position with its identity.
To repeat the article's A/A check on `startup` with a random order (the
published image accepts the newer `campaign.py` mounted over its own):

```sh
docker run --rm --cpuset-cpus=3 --cap-add PERFMON \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -v /sys/devices/virtual/powercap:/rapl:ro \
  -v "$PWD/scripts/campaign.py:/app/scripts/campaign.py:ro" \
  -v "$PWD/scripts/measure_exec.c:/app/scripts/measure_exec.c:ro" \
  -v "$PWD/results_csv:/app/results_csv" \
  compiler-benchmark-measure --programs startup --reps 50 --order random
python3 scripts/plot_results.py results_csv/<timestamp>
python3 scripts/paired_stats.py results_csv/<timestamp>
```

## Compilation cost

`build_cost.py` repeats the compilations of a subset of the matrix strictly
serially, several times per cell, with the cell order shuffled in every
repetition. It is not copied into the image, so mount it:

```sh
docker run --rm --cpuset-cpus=3 --entrypoint python3 \
  -v "$PWD/scripts/build_cost.py:/app/scripts/build_cost.py" \
  -v "$PWD/results_csv:/app/results_csv" \
  compiler-benchmark-measure \
  scripts/build_cost.py --matrix config/matrix.yaml --programs suma --reps 10
```

Results go to `results_csv/<timestamp>-build/` (`builds.csv`,
`build_summary.csv`, `environment.txt`).

## Energy window

In the published campaign, `measure_exec.c` read RAPL before `fork` and after
`wait4`, so the energy window was slightly longer than the wall-clock window.
`rapl_window_check.c` is that wrapper instrumented to report the difference;
its header gives the exact `docker run` invocation. The current
`measure_exec.c` reads RAPL right before starting the clock, so the two
windows coincide in future campaigns.

## SMT state and store-buffer stalls

We first attributed the copy workload's slowdown with the pinned core's SMT
sibling offline to a statically partitioned store buffer. `smt_stalls.sh`
tests that hypothesis: it alternates the sibling between offline and online
over several rounds and, in each state, runs `smt_stalls.py` inside the
image. That script compiles the selected cells with `campaign.py`'s own code
(the binaries are byte-identical to the campaign's) and runs each one
through `count_events.c`, which reads cycles, instructions,
`RESOURCE_STALLS.SB` and `RESOURCE_STALLS.ANY` as one counter group. By
default it measures `copy` (`final`) with and without `_FORTIFY_SOURCE=2`
and `sum` as the control, on g++ and clang++ at `-O3`.

```sh
sudo sysctl kernel.perf_event_paranoid=1      # restore afterwards
sudo CPU=3 SIBLING=7 ROUNDS=3 REPS=20 scripts/smt_stalls.sh
```

It must run as root (CPU hotplug) and restores the sibling's state on exit.
Results go to `results_csv/<timestamp>-smt-stalls/` (`stalls.csv`,
`binaries.csv`, one `environment-<state>-<round>.txt` per container).
The default event encodings are for Skylake; pass `--events` to
`smt_stalls.py` for other microarchitectures.

The published run (`results_csv/20261022-060910-smt-stalls`) reproduced the
effect (copy baselines 2.8x slower offline at the same instruction count)
but **refuted the hypothesis**: `RESOURCE_STALLS.SB` recorded only a few
hundred cycles per execution of `copy` in either state, and all
resource-related allocation stalls together account for less than 8% of
the cycles the offline state adds. The mechanism remains open.

## Reproducing the article

There are three levels of reproduction, with different requirements.

1. **Re-running the analysis** on the published data needs only Python and
   regenerates the article's tables, per-cell statistics
   (`figures/cell_stats.csv`), and paired statistics. The figures render
   identically; their PDF files are byte-identical only with the same
   matplotlib version (3.7.1) and creation date, which are embedded in them:

   ```sh
   pip3 install -r requirements.txt
   D=results_csv/20260720-114151-definitive
   python3 scripts/analyze.py $D
   python3 scripts/plot_results.py $D
   python3 scripts/paired_stats.py $D
   ```

2. **Rebuilding the binaries** needs the image pinned by digest. The
   article's campaign used
   `ghcr.io/reverseame/compilers-benchmark-comparator@sha256:1840aca51f5ac12438438e429215f8e90f7a1c68d52b5dbf37bffcb6dd049163`
   (rustc 1.98.0-nightly 096694416 2026-06-29, GCC 14.2.0-19, Clang 19.1.7,
   glibc 2.41). Its built-in `config/matrix.yaml` predates the campaign's,
   which adds Rustc's `stack_protector_all` cells, so the campaign mounted
   the repository's matrix over it, and so should any run with this image:

   ```sh
   docker run --rm --cpuset-cpus=3 --cap-add PERFMON \
     --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
     -v /sys/devices/virtual/powercap:/rapl:ro \
     -v "$PWD/config/matrix.yaml:/app/config/matrix.yaml:ro" \
     -v "$PWD/results_csv:/app/results_csv" \
     ghcr.io/reverseame/compilers-benchmark-comparator@sha256:1840aca51f5ac12438438e429215f8e90f7a1c68d52b5dbf37bffcb6dd049163 \
     --reps 50 --keep-binaries
   ```

   Compare the `sha256` column of the new `binaries.csv` with the published
   one. Rebuilding `Dockerfile.measure` from a later commit produces a
   different image digest and may install a different nightly.

3. **Repeating the timings** additionally needs the same machine
   configuration: an i7-6700 (Skylake), governor `performance`, turbo off,
   the container pinned to CPU 3, and CPU 7 (its SMT sibling) offline, as in
   "Running on a server". Absolute times, IPC, energy, and some flag ratios
   are host-dependent; on other hardware, expect the classification of the
   options to hold rather than the exact numbers.

The scripts in this commit are not byte-identical to those that produced
the July 2026 campaigns. The image contains the scripts of that time; the
later commits added the `--order` option and the `position` column to
`campaign.py`, moved the RAPL reads in `measure_exec.c` to coincide with
the wall clock (see "Energy window"), recorded `strip --version`, and added
the post-processing and follow-up scripts. Mount the newer scripts over the
image, as in the commands above, only for the follow-up experiments.

### Published data

| Directory under `results_csv/` | Role in the article |
|---|---|
| `20260720-114151-definitive` | Reported campaign: every number of the article unless stated otherwise (SMT sibling offline, 50 reps, counters and energy) |
| `20260708-165104-server` | Control sweep with the SMT sibling online (10 reps, loop programs). GCC and Clang binaries are byte-identical to the definitive campaign's; Rustc used a different nightly (f46ec5218 2026-06-30, not 096694416 2026-06-29), so its binaries differ |
| `20260709-100937-final`, `20260709-181237-final-perf`, `20260711-061031-final-energy` | Earlier full campaigns, used for the between-campaign reproducibility and memory-portability checks |
| `20260719-210130-rustc-canary` | Supplementary Rustc `-Z stack-protector` sweep, superseded by the definitive campaign |
| `20261021-093518-build` | Isolated build cost on a second host (i7-9700K) |
| `20261022-060156-build` | Isolated build cost on the campaign host |
| `20261022-060542-random-order` | `startup` with the order shuffled in every sweep (host kernel 6.1.0-53, newer wrapper) |
| `20261022-060910-smt-stalls` | Store-buffer stall counters, sibling offline and online |
| `20261022-060149-rapl-window` | Extra RAPL interval of the published wrapper |
| `20261022-060149-followup` | Log and host capture of the October follow-up runs |

## Technologies

- **Python**: campaign driver, data handling, tables and figures.
- **C**: measurement wrapper (`fork`/`execv`/`wait4`).
- **Docker**: packaging and reproducible deployment of the toolchains.
- **C++** and **Rust**: the languages whose compilers are under study.
