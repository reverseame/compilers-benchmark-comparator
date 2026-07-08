#!/usr/bin/env python3
"""Generate the paper's figures from a measurement-campaign results directory.

Reads runs.csv and binaries.csv as produced by scripts/campaign.py and emits,
under <results_dir>/figures/:

  time_vs_opt_<prog>.pdf        median runtime vs optimization level, one line
                                per compiler, with a 95% bootstrap CI band
  overhead_cheap_<prog>.pdf     % runtime overhead vs same-opt baseline at -O3
                                for the inexpensive flags, with 95% CI whiskers
  overhead_costly_<prog>.pdf    slowdown factor (x) for sanitizers and
                                language-level runtime checks, with 95% CI
  rss_ratio_<prog>.pdf          peak-RSS ratio vs baseline at -O3, with 95% CI
  size_<prog>.pdf               stripped binary size per flag at -O3
  cell_stats.csv                per-cell median and 95% CI for time and RSS
                                (the numeric source for every figure)

Statistics: the point estimate is always the MEDIAN of the timed repetitions
(robust to interference outliers); uncertainty is a 95% percentile bootstrap
confidence interval. For ratios (overhead, slowdown, RSS ratio) the flag and
baseline samples are resampled independently and the CI is taken over the
ratio of medians. The bootstrap RNG is seeded, so output is reproducible.

Only valid runs are used (is_warmup=0, exit_code=0, output_ok=1).

Usage:
  python3 scripts/plot_results.py results_csv/<timestamp> [--resamples N]

Requires matplotlib (pip install -r requirements.txt); everything else is
standard library.
"""

import argparse
import csv
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SEED = 20260708

COMPILERS = ["g++", "clang++", "rustc"]
COMPILER_LABEL = {"g++": "GCC", "clang++": "Clang", "rustc": "Rustc"}
COMPILER_COLOR = {"g++": "#4C72B0", "clang++": "#DD8452", "rustc": "#55A868"}

# rustc opt levels normalized to the -O* labels used by GCC/Clang.
OPT_LABEL = {
    "-C opt-level=0": "-O0", "-C opt-level=1": "-O1", "-C opt-level=2": "-O2",
    "-C opt-level=3": "-O3", "-C opt-level=s": "-Os", "-C opt-level=z": "-Oz",
}
OPT_ORDER = ["-O0", "-O1", "-O2", "-O3", "-Os", "-Oz", "-Ofast"]
O3 = {"g++": "-O3", "clang++": "-O3", "rustc": "-C opt-level=3"}

# Flags whose cost is expected to be a multiplier rather than a few percent:
# sanitizers and language-level runtime checks. They get their own figure on
# a factor scale; everything else goes on a percent scale.
COSTLY_FLAGS = {
    "asan", "msan", "ubsan", "lsan", "safe_stack",
    "overflow_checks", "debug_assertions",
}


def opt_label(opt):
    return OPT_LABEL.get(opt, opt)


def load_runs(results_dir):
    """runs[(compiler, program, opt, flag_id)] -> {'wall': [...], 'rss': [...]}"""
    runs = defaultdict(lambda: {"wall": [], "rss": []})
    programs = set()
    with open(results_dir / "runs.csv") as f:
        for row in csv.DictReader(f):
            if row["is_warmup"] != "0":
                continue
            if row["exit_code"] != "0" or row["output_ok"] != "1":
                continue
            key = (row["compiler"], row["program"], row["opt"], row["flag_id"])
            runs[key]["wall"].append(float(row["wall_s"]) * 1000.0)  # ms
            runs[key]["rss"].append(float(row["max_rss_kb"]))
            programs.add(row["program"])
    return runs, sorted(programs)


def load_binaries(results_dir):
    binaries = {}
    with open(results_dir / "binaries.csv") as f:
        for row in csv.DictReader(f):
            if row["compile_ok"] != "1":
                continue
            binaries[(row["compiler"], row["program"], row["opt"], row["flag_id"])] = row
    return binaries


def boot_ci_median(values, rng, resamples):
    """95% percentile bootstrap CI for the median of one sample."""
    n = len(values)
    meds = sorted(
        statistics.median(rng.choices(values, k=n)) for _ in range(resamples)
    )
    return meds[int(0.025 * resamples)], meds[int(0.975 * resamples)]


def boot_ci_ratio(num, den, rng, resamples):
    """95% percentile bootstrap CI for median(num)/median(den),
    resampling both samples independently."""
    ratios = sorted(
        statistics.median(rng.choices(num, k=len(num)))
        / statistics.median(rng.choices(den, k=len(den)))
        for _ in range(resamples)
    )
    return ratios[int(0.025 * resamples)], ratios[int(0.975 * resamples)]


def new_axes(width=6.0, height=3.4):
    fig, ax = plt.subplots(figsize=(width, height))
    ax.grid(True, axis="both", linewidth=0.4, alpha=0.4)
    ax.set_axisbelow(True)
    return fig, ax


def save(fig, outdir, name):
    fig.tight_layout()
    fig.savefig(outdir / name)
    plt.close(fig)
    print(f"  wrote figures/{name}")


def fig_time_vs_opt(runs, program, outdir, rng, resamples):
    fig, ax = new_axes()
    # One shared x axis across compilers (not every compiler has every level).
    present = {
        opt_label(o) for (c, p, o, f) in runs
        if p == program and f == "baseline"
    }
    labels = [l for l in OPT_ORDER if l in present]
    xpos = {l: i for i, l in enumerate(labels)}
    for comp in COMPILERS:
        x, meds, lo, hi = [], [], [], []
        for label in labels:
            found = [
                o for (c, p, o, f) in runs
                if c == comp and p == program and f == "baseline"
                and opt_label(o) == label
            ]
            if not found:
                continue
            wall = runs[(comp, program, found[0], "baseline")]["wall"]
            ci = boot_ci_median(wall, rng, resamples)
            x.append(xpos[label])
            meds.append(statistics.median(wall))
            lo.append(ci[0])
            hi.append(ci[1])
        color = COMPILER_COLOR[comp]
        ax.plot(x, meds, marker="o", markersize=4, color=color,
                label=COMPILER_LABEL[comp])
        ax.fill_between(x, lo, hi, color=color, alpha=0.25, linewidth=0)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yscale("log")
    ax.set_ylabel("Runtime (ms, log scale)")
    ax.set_xlabel("Optimization level")
    ax.legend(frameon=False)
    save(fig, outdir, f"time_vs_opt_{program}.pdf")


def overhead_data(runs, program, costly, rng, resamples):
    """[(flag, comp, ratio, lo, hi)] for flags at -O3 vs the -O3 baseline."""
    data = []
    flags = sorted({
        f for (c, p, o, f) in runs
        if p == program and o == O3[c] and f != "baseline"
        and (f in COSTLY_FLAGS) == costly
    })
    for flag in flags:
        for comp in COMPILERS:
            cell = runs.get((comp, program, O3[comp], flag))
            base = runs.get((comp, program, O3[comp], "baseline"))
            if not cell or not base:
                continue
            ratio = statistics.median(cell["wall"]) / statistics.median(base["wall"])
            lo, hi = boot_ci_ratio(cell["wall"], base["wall"], rng, resamples)
            data.append((flag, comp, ratio, lo, hi))
    return flags, data


def grouped_barh(ax, flags, data, to_x):
    """Horizontal bars grouped by flag, one bar per compiler, with CI whiskers."""
    bar_h = 0.8 / len(COMPILERS)
    ypos = {flag: i for i, flag in enumerate(flags)}
    for j, comp in enumerate(COMPILERS):
        ys, xs, err_lo, err_hi = [], [], [], []
        for (flag, c, ratio, lo, hi) in data:
            if c != comp:
                continue
            y = ypos[flag] + (j - (len(COMPILERS) - 1) / 2) * bar_h
            ys.append(y)
            xs.append(to_x(ratio))
            err_lo.append(to_x(ratio) - to_x(lo))
            err_hi.append(to_x(hi) - to_x(ratio))
        ax.barh(ys, xs, height=bar_h * 0.9, color=COMPILER_COLOR[comp],
                label=COMPILER_LABEL[comp])
        ax.errorbar(xs, ys, xerr=[err_lo, err_hi], fmt="none",
                    ecolor="black", elinewidth=0.7, capsize=1.5)
    ax.set_yticks(range(len(flags)), flags)
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=8)


def fig_overhead_cheap(runs, program, outdir, rng, resamples):
    flags, data = overhead_data(runs, program, costly=False,
                                rng=rng, resamples=resamples)
    fig, ax = new_axes(height=0.32 * len(flags) + 1.2)
    grouped_barh(ax, flags, data, to_x=lambda r: (r - 1.0) * 100.0)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Runtime overhead vs. baseline at -O3 (%)")
    save(fig, outdir, f"overhead_cheap_{program}.pdf")


def fig_overhead_costly(runs, program, outdir, rng, resamples):
    flags, data = overhead_data(runs, program, costly=True,
                                rng=rng, resamples=resamples)
    if not flags:
        return
    fig, ax = new_axes(height=0.4 * len(flags) + 1.2)
    grouped_barh(ax, flags, data, to_x=lambda r: r)
    ax.axvline(1, color="black", linewidth=0.8)
    ax.set_xlabel("Slowdown factor vs. baseline at -O3 (x)")
    save(fig, outdir, f"overhead_costly_{program}.pdf")


def fig_rss_ratio(runs, program, outdir, rng, resamples):
    flags = sorted({
        f for (c, p, o, f) in runs
        if p == program and o == O3[c] and f != "baseline"
    })
    data = []
    for flag in flags:
        for comp in COMPILERS:
            cell = runs.get((comp, program, O3[comp], flag))
            base = runs.get((comp, program, O3[comp], "baseline"))
            if not cell or not base:
                continue
            ratio = statistics.median(cell["rss"]) / statistics.median(base["rss"])
            lo, hi = boot_ci_ratio(cell["rss"], base["rss"], rng, resamples)
            data.append((flag, comp, ratio, lo, hi))
    fig, ax = new_axes(height=0.32 * len(flags) + 1.2)
    grouped_barh(ax, flags, data, to_x=lambda r: r)
    ax.axvline(1, color="black", linewidth=0.8)
    ax.set_xlabel("Peak-RSS ratio vs. baseline at -O3 (x)")
    save(fig, outdir, f"rss_ratio_{program}.pdf")


def fig_size(binaries, program, outdir):
    flags = sorted({
        f for (c, p, o, f) in binaries if p == program and o == O3[c]
    })
    fig, ax = new_axes(height=0.32 * len(flags) + 1.2)
    bar_h = 0.8 / len(COMPILERS)
    for j, comp in enumerate(COMPILERS):
        ys, xs = [], []
        for i, flag in enumerate(flags):
            row = binaries.get((comp, program, O3[comp], flag))
            if not row:
                continue
            ys.append(i + (j - (len(COMPILERS) - 1) / 2) * bar_h)
            xs.append(int(row["size_stripped_bytes"]) / 1024.0)
        ax.barh(ys, xs, height=bar_h * 0.9, color=COMPILER_COLOR[comp],
                label=COMPILER_LABEL[comp])
    ax.set_yticks(range(len(flags)), flags)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("Stripped binary size at -O3 (KB, log scale)")
    ax.legend(frameon=False, fontsize=8)
    save(fig, outdir, f"size_{program}.pdf")


def write_cell_stats(runs, results_dir, rng, resamples):
    """Per-cell medians and CIs, plus overhead vs the same-opt baseline."""
    out = results_dir / "figures" / "cell_stats.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "compiler", "program", "opt", "flag_id", "n",
            "time_ms_median", "time_ms_ci95_lo", "time_ms_ci95_hi",
            "rss_kb_median", "rss_kb_ci95_lo", "rss_kb_ci95_hi",
            "overhead_vs_baseline", "overhead_ci95_lo", "overhead_ci95_hi",
        ])
        for key in sorted(runs):
            comp, prog, opt, flag = key
            wall, rss = runs[key]["wall"], runs[key]["rss"]
            t_lo, t_hi = boot_ci_median(wall, rng, resamples)
            r_lo, r_hi = boot_ci_median(rss, rng, resamples)
            row = [
                comp, prog, opt, flag, len(wall),
                f"{statistics.median(wall):.3f}", f"{t_lo:.3f}", f"{t_hi:.3f}",
                f"{statistics.median(rss):.0f}", f"{r_lo:.0f}", f"{r_hi:.0f}",
            ]
            base = runs.get((comp, prog, opt, "baseline"))
            if flag != "baseline" and base:
                ratio = statistics.median(wall) / statistics.median(base["wall"])
                o_lo, o_hi = boot_ci_ratio(wall, base["wall"], rng, resamples)
                row += [f"{ratio:.4f}", f"{o_lo:.4f}", f"{o_hi:.4f}"]
            else:
                row += ["", "", ""]
            w.writerow(row)
    print(f"  wrote figures/{out.name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results_dir", type=Path,
                    help="campaign output directory (contains runs.csv)")
    ap.add_argument("--resamples", type=int, default=5000,
                    help="bootstrap resamples for the CIs (default: 5000)")
    args = ap.parse_args()

    if not (args.results_dir / "runs.csv").exists():
        sys.exit(f"error: {args.results_dir}/runs.csv not found")
    runs, programs = load_runs(args.results_dir)
    binaries = load_binaries(args.results_dir)
    outdir = args.results_dir / "figures"
    outdir.mkdir(exist_ok=True)

    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42})
    rng = random.Random(SEED)

    for program in programs:
        print(f"[plot] {program}")
        fig_time_vs_opt(runs, program, outdir, rng, args.resamples)
        fig_overhead_cheap(runs, program, outdir, rng, args.resamples)
        fig_overhead_costly(runs, program, outdir, rng, args.resamples)
        fig_rss_ratio(runs, program, outdir, rng, args.resamples)
        fig_size(binaries, program, outdir)
    print("[plot] cell statistics")
    write_cell_stats(runs, args.results_dir, rng, args.resamples)


if __name__ == "__main__":
    main()
