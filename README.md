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
- **config/matrix.yaml**: the experimental matrix (compilers × optimization
  levels × security flags × programs). Single source of truth for the
  campaign.
- **programs**: benchmark source programs. Each benchmark exists as a
  semantically equivalent `.cpp`/`.rs` pair.
- **Dockerfile.measure** and **docker-compose.yml**: lean container image for
  running the campaign on a server.

## Measurement campaign (v2, CSV output)

The measurement campaign runs through `scripts/campaign.py`:

- The experimental matrix is defined in **`config/matrix.yaml`**; adding a
  compiler or a flag requires no code changes.
- Compilation runs in parallel, but **timed executions are strictly
  sequential** and sweep-major (one full pass over all binaries per
  repetition, so slow drift affects all cells equally).
- Every execution is recorded **individually** in `runs.csv` (no
  aggregation): wall-clock time (`CLOCK_MONOTONIC`), user/system CPU time,
  peak RSS and **exit status** — all from the same execution, via `wait4(2)`.
  A warmup sweep is recorded flagged with `is_warmup=1`.
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

# 3. Launch the campaign pinned to isolated cores, with no CPU limits:
docker run --rm --cpuset-cpus=2,3 --security-opt seccomp=unconfined \
  -v "$PWD/results_csv:/app/results_csv" \
  compiler-benchmark-measure --reps 50
```

Useful options: `--programs suma,final`, `--compilers g++,clang++,rustc`,
`--reps N`, `--keep-binaries` (keeps the compiled binaries next to the CSVs
so they can be archived as an artifact).

Results are written to
`results_csv/<timestamp>/{runs.csv,binaries.csv,environment.txt,matrix.yaml}`.

If the machine has SMT (hyper-threading), also keep the pinned core's
sibling thread idle (e.g. pin to core 3 and leave core 7 unused on a
4-core/8-thread CPU); a busy sibling shows up as occasional outlier
repetitions.

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

## Technologies

- **Python**: campaign driver, data handling, tables and figures.
- **C**: measurement wrapper (`fork`/`execv`/`wait4`).
- **Docker**: packaging and reproducible deployment of the toolchains.
- **C++** and **Rust**: the languages whose compilers are under study.
