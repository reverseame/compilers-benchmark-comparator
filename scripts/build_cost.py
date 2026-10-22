#!/usr/bin/env python3
"""Isolated, repeated measurement of compilation cost.

campaign.py compiles every cell once, in a thread pool, before the timed
executions; inside a container pinned to one CPU those compilations share
that CPU. This script repeats the compilations of a subset of the matrix
strictly serially, one compiler process at a time, several times per cell,
with the cell order shuffled (seeded) in every repetition, so that build
cost can be reported with a median and a spread.

CPU time (user+sys) and peak RSS come from the wait4(2) rusage of the
compiler driver, which includes the subprocesses it waits for (cc1plus, as,
ld, the linker invoked by rustc).

Usage (inside the measurement image, pinned to one CPU):
  docker run --rm --cpuset-cpus=3 --entrypoint python3 \\
      -v $PWD/scripts/build_cost.py:/app/scripts/build_cost.py \\
      -v $PWD/results_csv:/app/results_csv \\
      <image> scripts/build_cost.py --matrix config/matrix.yaml \\
      --programs suma --reps 10

Outputs (in results_csv/<timestamp>-build/):
  builds.csv        one row per compilation
  build_summary.csv per-cell median CPU time, IQR, and ratio to baseline
  environment.txt   tool versions and CPU affinity

Requires PyYAML (present in the measurement image).
"""

import argparse
import csv
import os
import random
import shlex
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

SEED = 20260708
# Release level used for the build-cost comparison in the paper.
DEFAULT_OPT = {"g++": "-O3", "clang++": "-O3", "rustc": "-C opt-level=3"}


def tool_version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception as e:
        return f"unavailable ({e})"


def compile_once(cmd):
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    _, status, ru = os.wait4(p.pid, 0)  # blocking: no polling delay
    wall = time.monotonic() - t0
    p.returncode = 0  # reaped by wait4; silence Popen's destructor
    ok = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
    return ok, wall, ru.ru_utime + ru.ru_stime, ru.ru_maxrss


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--matrix", default="config/matrix.yaml")
    ap.add_argument("--programs", default="suma")
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--out", default="results_csv")
    args = ap.parse_args()

    matrix = yaml.safe_load(Path(args.matrix).read_text())
    root = Path(__file__).resolve().parent.parent
    src_dir = root / "programs"
    out_dir = Path(args.out) / (time.strftime("%Y%m%d-%H%M%S", time.gmtime())
                                + "-build")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())

    env = [f"date_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
           f"cpu_affinity: {sorted(os.sched_getaffinity(0))}",
           f"nproc: {os.cpu_count()}",
           f"reps: {args.reps}", f"seed: {SEED}"]
    for name, cmd in (("g++", ["g++", "--version"]),
                      ("clang++", ["clang++", "--version"]),
                      ("rustc", ["rustc", "--version"]),
                      ("strip", ["strip", "--version"]),
                      ("ld", ["ld", "--version"])):
        env.append(f"{name}: {tool_version(cmd)}")
    try:
        model = [l.split(":", 1)[1].strip()
                 for l in Path("/proc/cpuinfo").read_text().splitlines()
                 if l.startswith("model name")][0]
        env.append(f"cpu_model: {model}")
    except (OSError, IndexError):
        pass
    (out_dir / "environment.txt").write_text("\n".join(env) + "\n")

    cells = []
    for comp_name, comp in matrix["compilers"].items():
        opt = DEFAULT_OPT[comp_name]
        for prog in filter(None, args.programs.split(",")):
            src = src_dir / f"{prog}.{comp['source_ext']}"
            for flag_id, sec in comp["security_flags"].items():
                exe = tmp / f"{comp_name}__{prog}__{flag_id}"
                cmd = comp["command"].format(src=str(src), opt=opt,
                                             flags=sec, out=str(exe))
                cells.append((comp_name, prog, opt, flag_id,
                              shlex.split(" ".join(cmd.split()))))

    rng = random.Random(SEED)
    rows = []
    for rep in range(args.reps):
        order = cells[:]
        rng.shuffle(order)
        print(f"[build] repetition {rep + 1}/{args.reps}", flush=True)
        for comp_name, prog, opt, flag_id, cmd in order:
            ok, wall, cpu, rss = compile_once(cmd)
            rows.append({"compiler": comp_name, "program": prog, "opt": opt,
                         "flag_id": flag_id, "rep": rep, "ok": int(ok),
                         "wall_s": f"{wall:.4f}", "cpu_s": f"{cpu:.4f}",
                         "max_rss_kb": rss})
    with open(out_dir / "builds.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    by_cell = {}
    for r in rows:
        if r["ok"]:
            key = (r["compiler"], r["program"], r["opt"], r["flag_id"])
            by_cell.setdefault(key, []).append(float(r["cpu_s"]))
    summary = []
    for key, cpu in sorted(by_cell.items()):
        base = by_cell.get(key[:3] + ("baseline",))
        q = statistics.quantiles(cpu, n=4) if len(cpu) > 1 else [cpu[0]] * 3
        med = statistics.median(cpu)
        summary.append({"compiler": key[0], "program": key[1], "opt": key[2],
                        "flag_id": key[3], "n": len(cpu),
                        "cpu_s_median": f"{med:.4f}",
                        "cpu_s_q1": f"{q[0]:.4f}", "cpu_s_q3": f"{q[2]:.4f}",
                        "ratio_vs_baseline":
                            f"{med / statistics.median(base):.3f}"
                            if base else ""})
    with open(out_dir / "build_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    print(f"[build] done. Results in {out_dir}")


if __name__ == "__main__":
    main()
