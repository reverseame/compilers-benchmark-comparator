#!/usr/bin/env python3
"""Paired (sweep-blocked) bootstrap, A/A control, and baseline ELF report.

Complements plot_results.py, whose ratio CIs resample a flag cell and its
baseline independently. Here the two cells are resampled together by sweep:
every bootstrap replicate draws sweep indices with replacement and takes the
ratio of medians over the same sweeps for both cells, so conditions shared by
a sweep (temperature, frequency, background activity) are kept paired.

The script also uses the cells whose binary is byte-identical to its baseline
(same SHA-256) as an A/A control: any difference they show is measurement
noise or run-order position, never a flag effect.

Only valid measurements are used: is_warmup == 0 and output_ok == 1.

Usage:
  python3 scripts/paired_stats.py results_csv/<timestamp> [--resamples N]

Outputs (in <results>/tables):
  paired_stats.txt   baseline ELF properties, redundant (byte-identical)
                     cells, classical-defense bounds, A/A control
  paired_cells.csv   per-cell paired ratio of medians and CIs

Requires only the Python standard library.
"""

import argparse
import csv
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

SEED = 20260708
RELEASE = {"-O2", "-O3", "-Ofast", "-C opt-level=2", "-C opt-level=3"}
LOOPS = ("suma", "final")
# Flags grouped as "classical" in the paper (including the disabling and
# weakening variants, which share the same cost mechanisms).
CLASSICAL = {"stack_protector", "stack_protector_strong", "stack_protector_all",
             "stack_protector_none", "no_stack_protector", "relro_full",
             "pie", "no_pie", "noexecstack", "execstack"}
# Placement outliers excluded from the classical bound (see the paper).
EXCLUDED = {("clang++", "suma", "-O2", "no_pie"),
            ("clang++", "suma", "-O3", "no_pie"),
            ("clang++", "suma", "-Ofast", "no_pie")}


def load(results_dir):
    runs = defaultdict(dict)  # key -> {sweep: wall_s}
    with open(results_dir / "runs.csv") as f:
        for row in csv.DictReader(f):
            if row["is_warmup"] == "1" or row["output_ok"] != "1":
                continue
            key = (row["compiler"], row["program"], row["opt"], row["flag_id"])
            runs[key][int(row["sweep"])] = float(row["wall_s"])
    with open(results_dir / "binaries.csv") as f:
        binaries = {(r["compiler"], r["program"], r["opt"], r["flag_id"]): r
                    for r in csv.DictReader(f)}
    return runs, binaries


def paired_quantiles(cell, base, rng, resamples, qs):
    """Ratio of medians over a common set of resampled sweeps."""
    sweeps = sorted(set(cell) & set(base))
    n = len(sweeps)
    ratios = []
    for _ in range(resamples):
        pick = rng.choices(sweeps, k=n)
        ratios.append(statistics.median(cell[s] for s in pick)
                      / statistics.median(base[s] for s in pick))
    ratios.sort()
    return [ratios[min(int(q * resamples), resamples - 1)] for q in qs]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("--resamples", type=int, default=5000,
                    help="bootstrap resamples per cell (default: 5000)")
    ap.add_argument("--family-resamples", type=int, default=40000,
                    help="resamples for the Bonferroni family bound "
                         "(default: 40000)")
    args = ap.parse_args()
    runs, binaries = load(args.results_dir)
    rng = random.Random(SEED)
    out = []

    def base_of(key):
        return key[:3] + ("baseline",)

    def identical(key):
        b = binaries.get(base_of(key))
        return b is not None and binaries[key]["sha256"] == b["sha256"]

    # ---- baseline ELF properties ------------------------------------------
    out.append("== ELF properties of the empty-flag baselines (checksec)")
    props = defaultdict(Counter)
    for key, b in binaries.items():
        if key[3] == "baseline" and b["compile_ok"] == "1":
            props[key[0]][(b["pie"], b["nx"], b["relro"], b["canary"],
                           b["fortified"])] += 1
    for comp, c in sorted(props.items()):
        for (pie, nx, relro, canary, fort), n in c.items():
            out.append(f"{comp:8s} pie={pie} nx={nx} relro={relro} "
                       f"canary={canary} fortified={fort}  ({n} binaries)")

    # ---- redundant cells --------------------------------------------------
    out.append("\n== Cells byte-identical to their same-level baseline")
    tot, same = Counter(), Counter()
    for key, b in binaries.items():
        if key[3] == "baseline" or b["compile_ok"] != "1":
            continue
        tot[(key[0], key[3])] += 1
        same[(key[0], key[3])] += identical(key)
    for k in sorted(tot):
        if same[k]:
            out.append(f"{k[0]:8s} {k[1]:24s} {same[k]:3d}/{tot[k]}")

    # ---- per-cell paired CIs ----------------------------------------------
    rows = []
    for key in sorted(runs):
        if key[3] == "baseline" or base_of(key) not in runs:
            continue
        cell, base = runs[key], runs[base_of(key)]
        lo, hi = paired_quantiles(cell, base, rng, args.resamples,
                                  (0.025, 0.975))
        ratio = (statistics.median(cell.values())
                 / statistics.median(base.values()))
        delta_us = (statistics.median(cell.values())
                    - statistics.median(base.values())) * 1e6
        rows.append({"compiler": key[0], "program": key[1], "opt": key[2],
                     "flag_id": key[3], "identical": int(identical(key)),
                     "ratio": f"{ratio:.4f}", "delta_us": f"{delta_us:.1f}",
                     "paired_ci95_lo": f"{lo:.4f}",
                     "paired_ci95_hi": f"{hi:.4f}"})
    tables = args.results_dir / "tables"
    tables.mkdir(exist_ok=True)
    with open(tables / "paired_cells.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    by_key = {(r["compiler"], r["program"], r["opt"], r["flag_id"]): r
              for r in rows}

    # ---- classical defenses at the release levels -------------------------
    sel = [k for k in by_key if k[2] in RELEASE and k[3] in CLASSICAL
           and k[1] in LOOPS and k not in EXCLUDED]
    differ = [k for k in sel if not by_key[k]["identical"]]
    out.append(f"\n== Classical defenses, release levels, loop programs: "
               f"{len(sel)} cells ({len(sel) - len(differ)} byte-identical "
               f"to baseline, {len(differ)} different binaries)")
    ratios = [float(by_key[k]["ratio"]) for k in sel]
    out.append(f"ratio of medians: [{min(ratios):.4f}, {max(ratios):.4f}]")
    for name, group in (("all cells", sel), ("different binaries", differ)):
        hi = max((float(by_key[k]["paired_ci95_hi"]), k)
                 for k in group)
        out.append(f"max pointwise paired 95% upper limit, {name}: "
                   f"{hi[0]:.4f} {hi[1]}")
    m = len(differ)
    q = 1 - 0.05 / m
    fam = max((paired_quantiles(runs[k], runs[base_of(k)], rng,
                                args.family_resamples, (q,))[0], k)
              for k in differ)
    out.append(f"Bonferroni one-sided simultaneous 95% upper limit over the "
               f"{m} different binaries (quantile {q:.5f}, "
               f"{args.family_resamples} resamples): {fam[0]:.4f} {fam[1]}")

    # ---- A/A control ------------------------------------------------------
    out.append("\n== A/A control: byte-identical cells, all levels")
    indep = {}
    stats_csv = args.results_dir / "figures" / "cell_stats.csv"
    if stats_csv.exists():
        with open(stats_csv) as f:
            for r in csv.DictReader(f):
                if r["overhead_ci95_lo"]:
                    indep[(r["compiler"], r["program"], r["opt"],
                           r["flag_id"])] = (float(r["overhead_ci95_lo"]),
                                             float(r["overhead_ci95_hi"]))
    for prog in ("suma", "final", "startup"):
        aa = [k for k in by_key if k[1] == prog and by_key[k]["identical"]]
        if not aa:
            continue
        rs = [float(by_key[k]["ratio"]) for k in aa]
        ds = [float(by_key[k]["delta_us"]) for k in aa]
        paired_miss = sum(not (float(by_key[k]["paired_ci95_lo"]) <= 1
                               <= float(by_key[k]["paired_ci95_hi"]))
                          for k in aa)
        indep_miss = sum(k in indep and not (indep[k][0] <= 1 <= indep[k][1])
                         for k in aa)
        out.append(f"{prog:8s} n={len(aa):3d} ratio [{min(rs):.4f}, "
                   f"{max(rs):.4f}] delta_us [{min(ds):.0f}, {max(ds):.0f}] "
                   f"CI95 excludes 1: paired {paired_miss}, "
                   f"independent {indep_miss}")
        rel = [k for k in aa if k[2] in RELEASE]
        if rel:
            ds = [float(by_key[k]["delta_us"]) for k in rel]
            out.append(f"{'':8s} release levels only: n={len(rel)} "
                       f"delta_us [{min(ds):.0f}, {max(ds):.0f}]")

    text = "\n".join(out) + "\n"
    (tables / "paired_stats.txt").write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
