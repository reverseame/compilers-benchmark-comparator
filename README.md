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
- **config/matrix.yaml**: the experimental matrix (compilers × optimization
  levels × security flags × programs). Single source of truth for the
  campaign.
- **programs**: benchmark source programs. Each benchmark exists as a
  semantically equivalent `.cpp`/`.rs` pair.
- **Dockerfile.measure**: lean container image for running the campaign on a
  server.
- **Pipeline.sh**, **scripts/*.sh**, **scripts/*.py** (plots): legacy
  report/plot generation flow from the original TFG.
- **Dockerfile** and **docker-compose.yml**: container deployment for both
  flows.

## Measurement campaign (v2, CSV output)

The measurement campaign used for the article runs through
`scripts/campaign.py`, which replaces the per-compiler shell scripts
(`g++.sh`, `clang++.sh`, `rustc.sh`) for the measurement phase. Key
differences from the legacy flow:

- The experimental matrix is defined in **`config/matrix.yaml`**; adding a
  compiler or a flag requires no code changes.
- Compilation runs in parallel, but **timed executions are strictly
  sequential** (the legacy flow ran up to `nproc` combinations concurrently,
  invalidating the timings).
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
  compiler-benchmark-measure --reps 10
```

Useful options: `--programs suma,final`, `--compilers g++,clang++,rustc`,
`--reps N`, `--keep-binaries` (keeps the compiled binaries next to the CSVs
so they can be archived as an artifact).

Results are written to
`results_csv/<timestamp>/{runs.csv,binaries.csv,environment.txt,matrix.yaml}`.

## Legacy flow (TFG)

### Requirements

A program with the same base name in both languages (`.cpp` and `.rs`).

#### Native

- Debian-based system with: build-essential, clang, llvm, curl, python3,
  python3-pip, jq, bc, time, checksec, git, aha, wkhtmltopdf,
  texlive-latex-base, texlive-latex-extra, texlive-fonts-recommended, dvipng,
  cm-super, ghostscript, fonts-liberation, fonts-freefont-otf, binutils-dev,
  libcap-dev, libseccomp-dev, libasan8, libubsan1, libclang-rt-dev,
  python3-dev
- C++, clang++ and rustc (nightly) compilers installed.
- Python libraries: matplotlib, pandas, seaborn, numpy, scipy, statsmodels.
- Fonts configured for matplotlib (see Dockerfile).

```sh
sudo apt install build-essential clang llvm curl python3 python3-pip jq bc time checksec git aha texlive-latex-base texlive-latex-extra texlive-fonts-recommended dvipng cm-super ghostscript fonts-liberation fonts-freefont-otf binutils-dev libcap-dev libseccomp-dev libasan8 libubsan1 libclang-rt-dev python3-dev
```

> **Note on `wkhtmltopdf`**: recent distributions (Kali Linux, Debian 13,
> Ubuntu 24.04) no longer ship `wkhtmltopdf` in the official repositories.
> Install the `.deb` package manually:
> ```sh
> wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
> sudo apt install ./wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
> ```

```sh
pip3 install -r requirements.txt
```

#### Docker

- docker and docker-compose installed.
- At least 3 GB free for the image.

### Installation and usage

Clone the repository:
```sh
git clone https://github.com/DonJulve/Compilers-Benchmark-Comparator
```

**Note**:
 - `program_name` is the base name of the program to measure, without
   extension (for `suma.cpp`/`suma.rs`, pass `suma`).
 - `number_of_runs` is optional (default 1) and controls how many runs are
   averaged.

#### Native

```sh
./Pipeline <program_name> [<number_of_runs>]
```

#### Docker

```sh
# Pull the pre-built image (optional; docker-compose fetches it otherwise)
docker-compose pull

# Start containers
docker-compose up -d

# Run the benchmark
docker-compose run benchmark <program_name> [<number_of_runs>]
```

**Remove the image**
```sh
docker-compose down
docker rmi compiler-benchmark
```

## Technologies

- **Shell**: scripting language used by the legacy compile/run/measure flow.
- **Python**: campaign driver, data handling and plot generation.
- **Docker**: packaging and reproducible deployment of the toolchains.
- **C++** and **Rust**: the languages whose compilers are under study.
