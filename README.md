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
  are strictly sequential** and sweep-major (one full pass over all binaries per
  repetition, so slow drift affects all cells equally).
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

```sh
# 1. Prepare the host (outside the container):
sudo cpupower frequency-set -g performance      # governor
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo  # turbo off

# 2. Build the lean image (GCC 14.2 / Clang 19 from Debian trixie).
#    Pin the Rust nightly for reproducibility:
docker build -f Dockerfile.measure \
  --build-arg RUST_TOOLCHAIN=nightly-2026-07-01 \
  -t compiler-benchmark-measure .

# 3. Optional, for hardware counters and RAPL energy (see the metrics
#    section above; restore afterwards):
sudo sysctl kernel.perf_event_paranoid=1
sudo modprobe intel_rapl_msr

# 4. Launch the campaign pinned to isolated cores, with no CPU limits:
docker run --rm --cpuset-cpus=2,3 --cap-add PERFMON \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -v /sys/devices/virtual/powercap:/rapl:ro \
  -v "$PWD/results_csv:/app/results_csv" \
  compiler-benchmark-measure --reps 50
```

Useful options: `--programs suma,final`, `--compilers g++,clang++,rustc`,
`--reps N`, `--keep-binaries` (keeps the compiled binaries next to the CSVs
so they can be archived as an artifact).

Results are written to
`results_csv/<timestamp>/{runs.csv,binaries.csv,environment.txt,matrix.yaml}`.

If the machine has SMT (hyper-threading), take the pinned core's sibling
thread offline for the campaign (`echo 0 | sudo tee
/sys/devices/system/cpu/cpu7/online` for core 3 on a 4-core/8-thread CPU,
re-enable with `echo 1` afterwards): a busy sibling shows up as outlier
repetitions.

**Warning — SMT state changes more than noise.** On benchmarks with a
store-heavy hot loop (e.g. a `strcpy` loop inside libc) we measured
**~2.8x** runtime differences between otherwise identical campaigns
depending solely on whether the pinned core's sibling was online — with
byte-identical binaries and glibc's `ld.so --list-diagnostics` output
identical in both states, i.e. a hardware effect (the core appears to keep
its execution resources statically partitioned when the sibling is
hot-unplugged), not a software one. Pick one SMT state, keep it for every
campaign you intend to compare, and check it is recorded in
`environment.txt` (`smt_control` / `cpus_online`).

### How many repetitions?

One full sweep over the 618 binaries takes about 3 minutes on the reference
server, so the campaign scales linearly at roughly `3 min × (reps + 1)`:

| `--reps` | duration | note |
|---------:|---------:|------|
| 10       | ~30 min  | enough for smoke tests |
| 50       | ~2.5 h   | **recommended for the article**: CI half-width ≈ 0.3% of the median |
| 100      | ~5 h     | diminishing returns |

Measurement noise is ~1.5% (coefficient of variation), so the confidence
interval of the median shrinks below any effect of interest well before 100
repetitions; past that point you are measuring the machine, not the flags.
Statistics are computed downstream from the raw rows, so the choice of
`--reps` never changes the analysis code.

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
only, about 90 s); it does not need the container:

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

## Image used in the article

The article's campaign used the image
`ghcr.io/reverseame/compilers-benchmark-comparator@sha256:1840aca51f5ac12438438e429215f8e90f7a1c68d52b5dbf37bffcb6dd049163`,
built before the RAPL change to `measure_exec.c` and the `strip --version`
entry in `campaign.py`. Rebuilding `Dockerfile.measure` from a later commit
produces a different digest; use the digest above to reproduce the published
data, and mount the newer scripts into it as shown above.

## Technologies

- **Python**: campaign driver, data handling, tables and figures.
- **C**: measurement wrapper (`fork`/`execv`/`wait4`).
- **Docker**: packaging and reproducible deployment of the toolchains.
- **C++** and **Rust**: the languages whose compilers are under study.
