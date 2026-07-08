#!/usr/bin/env python3
"""Generate the paper's LaTeX tables and summary statistics from a campaign
results directory (runs.csv + binaries.csv).

Only valid measurements are used: is_warmup == 0 and output_ok == 1. Any
excluded rows are reported in summary.txt so silent data loss is impossible.

Usage:
  python3 scripts/analyze.py results_csv/<timestamp> [--out paper_tables]

Outputs (in --out, default <results>/tables):
  opt_time_<program>.tex        baseline time per optimization level/compiler
  overhead_O3_<program>.tex     per-flag time at -O3 vs same-level baseline
  mem_by_opt_<compiler>_<program>.tex  peak RSS per level, no hardening
  summary.txt                   key derived statistics + data-quality report

Requires only the Python standard library.
"""

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

O3 = {"g++": "-O3", "clang++": "-O3", "rustc": "-C opt-level=3"}
O0 = {"g++": "-O0", "clang++": "-O0", "rustc": "-C opt-level=0"}
OPT_LABEL = {  # canonical display order and labels
    "-O0": "-O0", "-C opt-level=0": "-O0",
    "-O1": "-O1", "-C opt-level=1": "-O1",
    "-O2": "-O2", "-C opt-level=2": "-O2",
    "-O3": "-O3", "-C opt-level=3": "-O3",
    "-Os": "-Os", "-C opt-level=s": "-Os",
    "-Oz": "-Oz", "-C opt-level=z": "-Oz",
    "-Ofast": "-Ofast",
}
OPT_ORDER = ["-O0", "-O1", "-O2", "-O3", "-Os", "-Oz", "-Ofast"]
COMPILERS = ["clang++", "g++", "rustc"]
COMP_LABEL = {"clang++": "Clang", "g++": "GCC", "rustc": "Rustc"}


def load(results_dir):
    runs, excluded = defaultdict(list), defaultdict(int)
    with open(results_dir / "runs.csv") as f:
        for row in csv.DictReader(f):
            key = (row["compiler"], row["program"], row["opt"], row["flag_id"])
            if row["is_warmup"] == "1":
                continue
            if row["output_ok"] != "1":
                excluded[key] += 1
                continue
            runs[key].append({"wall": float(row["wall_s"]),
                              "rss": int(row["max_rss_kb"])})
    binaries = {}
    with open(results_dir / "binaries.csv") as f:
        for row in csv.DictReader(f):
            key = (row["compiler"], row["program"], row["opt"], row["flag_id"])
            binaries[key] = row
    return runs, excluded, binaries


def mean_ms(runs, key):
    rows = runs.get(key)
    return statistics.mean(r["wall"] for r in rows) * 1000 if rows else None


def mean_rss(runs, key):
    rows = runs.get(key)
    return statistics.mean(r["rss"] for r in rows) if rows else None


def fmt(x, nd=2):
    return f"{x:.{nd}f}" if x is not None else "N/A"


def pct(new, base):
    if new is None or base is None or base == 0:
        return ""
    d = 100 * (new - base) / base
    return f"({'+' if d >= 0 else ''}{d:.0f}\\%)"


def opt_time_table(runs, program):
    """Baseline execution time per optimization level, one column per compiler."""
    lines = [
        "\\begin{tabular*}{\\columnwidth}{@{\\extracolsep\\fill}cccc@{\\extracolsep\\fill}}",
        "\\toprule",
        "\\textbf{Level} & \\textbf{Clang} & \\textbf{GCC} & \\textbf{Rustc} \\\\",
        "\\midrule",
    ]
    base = {c: mean_ms(runs, (c, program, O0[c], "baseline")) for c in COMPILERS}
    for lvl in OPT_ORDER:
        cells = []
        for c in COMPILERS:
            opt = next((o for o, l in OPT_LABEL.items()
                        if l == lvl and (c, program, o, "baseline") in runs), None)
            if opt is None:
                cells.append("N/A")
                continue
            t = mean_ms(runs, (c, program, opt, "baseline"))
            cells.append(f"{fmt(t)} {pct(t, base[c])}".strip()
                         if lvl != "-O0" else fmt(t))
        lines.append(f"\\texttt{{{lvl}}} & {cells[0]} & {cells[1]} & {cells[2]} \\\\")
    lines += ["\\bottomrule", "\\end{tabular*}"]
    return "\n".join(lines) + "\n"


def overhead_o3_table(runs, program, flag_ids):
    """baseline -> flag execution time at -O3 for selected flags."""
    lines = [
        "\\begin{tabular*}{\\columnwidth}{@{\\extracolsep\\fill}lccc@{\\extracolsep\\fill}}",
        "\\toprule",
        "\\textbf{Flag} & \\textbf{Clang} & \\textbf{GCC} & \\textbf{Rustc} \\\\",
        "\\midrule",
    ]
    for flag in flag_ids:
        cells = []
        for c in COMPILERS:
            b = mean_ms(runs, (c, program, O3[c], "baseline"))
            t = mean_ms(runs, (c, program, O3[c], flag))
            cells.append(f"{fmt(b)}$\\to${fmt(t)}" if t is not None else "N/A")
        label = flag.replace("_", "\\_")
        lines.append(f"\\texttt{{{label}}} & {cells[0]} & {cells[1]} & {cells[2]} \\\\")
    lines += ["\\bottomrule", "\\end{tabular*}"]
    return "\n".join(lines) + "\n"


def mem_table(runs, compiler, program):
    lines = [
        "\\begin{tabular*}{\\columnwidth}{@{\\extracolsep\\fill}lcc@{\\extracolsep\\fill}}",
        "\\toprule",
        "\\textbf{Level} & \\textbf{Memory} & \\textbf{$\\Delta$ vs.\\ \\texttt{-O0}} \\\\",
        "\\midrule",
    ]
    base = mean_rss(runs, (compiler, program, O0[compiler], "baseline"))
    for opt in [o for o in OPT_LABEL if (compiler, program, o, "baseline") in runs]:
        m = mean_rss(runs, (compiler, program, opt, "baseline"))
        delta = pct(m, base).strip("()") if opt != O0[compiler] else "--"
        lines.append(f"\\texttt{{{OPT_LABEL[opt]}}} & {m:.0f} & {delta} \\\\")
    lines += ["\\bottomrule", "\\end{tabular*}"]
    return "\n".join(lines) + "\n"


def summary(runs, excluded, binaries, programs):
    out = []
    total_rows = sum(len(v) for v in runs.values())
    out.append(f"valid timed executions: {total_rows}")
    out.append(f"cells with measurements: {len(runs)}")
    bad = sum(excluded.values())
    out.append(f"EXCLUDED executions (crash/wrong output): {bad}")
    for key, n in sorted(excluded.items()):
        out.append(f"  excluded {n:3d}: {' '.join(key)}")
    nc = [k for k, b in binaries.items() if b["compile_ok"] != "1"]
    out.append(f"compile failures: {len(nc)}")
    for k in nc:
        out.append(f"  no-compile: {' '.join(k)}")
    # headline stats per program
    for prog in programs:
        out.append(f"\n== {prog} ==")
        for c in COMPILERS:
            b = mean_ms(runs, (c, prog, O3[c], "baseline"))
            if b is None:
                continue
            worst_t, worst_f = None, ""
            for (cc, pp, oo, ff) in runs:
                if (cc, pp, oo) == (c, prog, O3[c]) and ff != "baseline":
                    t = mean_ms(runs, (cc, pp, oo, ff))
                    if t and (worst_t is None or t > worst_t):
                        worst_t, worst_f = t, ff
            out.append(f"{COMP_LABEL[c]}: baseline@O3 {fmt(b)} ms; "
                       f"worst flag {worst_f} = {fmt(worst_t)} ms "
                       f"({fmt(worst_t / b, 2)}x)" if worst_t else
                       f"{COMP_LABEL[c]}: baseline@O3 {fmt(b)} ms")
        # sanitizer memory multipliers
        for c in COMPILERS:
            b = mean_rss(runs, (c, prog, O3[c], "baseline"))
            a = mean_rss(runs, (c, prog, O3[c], "asan"))
            if b and a:
                out.append(f"{COMP_LABEL[c]}: ASan RSS {a:.0f} KB vs {b:.0f} KB "
                           f"({a / b:.1f}x)")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out_dir = args.out or (args.results / "tables")
    out_dir.mkdir(parents=True, exist_ok=True)

    runs, excluded, binaries = load(args.results)
    if not runs:
        sys.exit("no valid measurements found")
    programs = sorted({k[1] for k in runs})

    o3_flags = ["stack_protector_strong", "fortify2", "asan", "msan"]
    for prog in programs:
        (out_dir / f"opt_time_{prog}.tex").write_text(opt_time_table(runs, prog))
        (out_dir / f"overhead_O3_{prog}.tex").write_text(
            overhead_o3_table(runs, prog, o3_flags))
        for c in COMPILERS:
            if any(k[0] == c and k[1] == prog for k in runs):
                (out_dir / f"mem_by_opt_{c.replace('+','p')}_{prog}.tex").write_text(
                    mem_table(runs, c, prog))
    (out_dir / "summary.txt").write_text(
        summary(runs, excluded, binaries, programs))
    print(f"tables written to {out_dir}")


if __name__ == "__main__":
    main()
