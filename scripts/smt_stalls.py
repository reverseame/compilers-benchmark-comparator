#!/usr/bin/env python3
"""Store-buffer stalls with the measurement core's SMT sibling on and off.

Tests the hypothesis of the paper's threats-to-validity discussion: if the
copy workload slows down with the sibling offline because the core keeps its
store buffer partitioned, RESOURCE_STALLS.SB should rise substantially in the
offline state on the same binary, with no comparable shift on the arithmetic
loop (sum).

This script runs INSIDE the measurement image, once per SMT state; the host
side (toggling the sibling, alternating the states over several rounds) is
scripts/smt_stalls.sh, which is what you normally launch. Cells are compiled
with campaign.py's own code, so commands and flags are exactly those of the
campaign; every execution goes through count_events.c, with the cell order
shuffled (seeded) in every repetition.

Usage (normally via smt_stalls.sh):
  python3 scripts/smt_stalls.py --state offline --round 1 --out /app/out
      [--reps 20] [--cells g++:final:-O3:baseline,...] [--events sb=0x08a2]

Outputs (appended, so all states and rounds share the files):
  stalls.csv     one row per execution
  binaries.csv   one row per compiled cell, state and round (sha256, command)
  environment-<state>-<round>.txt

The default raw events are Skylake encodings (RESOURCE_STALLS.SB and
RESOURCE_STALLS.ANY); other microarchitectures need --events.
"""

import argparse
import csv
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

import campaign

SEED = 20260708
DEFAULT_CELLS = ",".join([
    "g++:final:-O3:baseline", "g++:final:-O3:fortify2",
    "clang++:final:-O3:baseline", "clang++:final:-O3:fortify2",
    "g++:suma:-O3:baseline", "clang++:suma:-O3:baseline",
])
DEFAULT_EVENTS = "resource_stalls_sb=0x08a2,resource_stalls_any=0x01a2"


def append_csv(path, header, rows):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True,
                    help="label of the SMT state (offline/online)")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--cells", default=DEFAULT_CELLS,
                    help="comma-separated compiler:program:opt:flag_id")
    ap.add_argument("--events", default=DEFAULT_EVENTS,
                    help="comma-separated name=raw_config")
    ap.add_argument("--matrix", default="config/matrix.yaml")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    root = Path(__file__).resolve().parent.parent
    src_dir = root / "programs"
    matrix = yaml.safe_load(Path(args.matrix).read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    tag = f"{args.state}-{args.round}"

    # the label must agree with what the kernel reports
    cpus_online = campaign.read_first("/sys/devices/system/cpu/online")
    env = [f"date_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
           f"state: {args.state}", f"round: {args.round}",
           f"cpus_online: {cpus_online}",
           f"smt_control: "
           f"{campaign.read_first('/sys/devices/system/cpu/smt/control')}",
           f"cpu_affinity: {sorted(os.sched_getaffinity(0))}",
           f"perf_event_paranoid: "
           f"{campaign.read_first('/proc/sys/kernel/perf_event_paranoid')}",
           f"events: {args.events}", f"reps: {args.reps}", f"seed: {SEED}"]
    (args.out / f"environment-{tag}.txt").write_text("\n".join(env) + "\n")
    print(f"[smt_stalls] state={args.state} round={args.round} "
          f"cpus_online={cpus_online}")

    bin_dir = Path(tempfile.mkdtemp())
    cells = []
    for spec in args.cells.split(","):
        comp, prog, opt, flag_id = spec.split(":")
        cell = campaign.Cell(
            compiler=comp, program=prog, opt=opt, flag_id=flag_id,
            sec_flags=matrix["compilers"][comp]["security_flags"][flag_id],
            expected_output=str(
                matrix["programs"][prog].get("expected_output", "")))
        campaign.compile_cell(cell, matrix, src_dir, bin_dir)
        if not cell.compile_ok:
            sys.exit(f"error: cannot compile {spec}: {cell.compile_stderr}")
        cells.append(cell)
    append_csv(args.out / "binaries.csv",
               ["state", "round", "compiler", "program", "opt", "flag_id",
                "compile_cmd", "sha256"],
               [[args.state, args.round, c.compiler, c.program, c.opt,
                 c.flag_id, c.command, c.sha256] for c in cells])

    counter = bin_dir / "count_events"
    subprocess.run(["gcc", "-O2", str(root / "scripts" / "count_events.c"),
                    "-o", str(counter)], check=True)

    names = [e.split("=")[0] for e in args.events.split(",")]
    header = ["state", "round", "cpus_online", "compiler", "program", "opt",
              "flag_id", "rep", "is_warmup", "wall_s", "exit_code",
              "output_ok", "running_ratio", "cycles", "instructions", *names]
    rng = random.Random(SEED + args.round)
    rows = []
    run_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    for rep in range(args.warmup + args.reps):
        order = cells[:]
        rng.shuffle(order)
        for c in order:
            with tempfile.NamedTemporaryFile() as out_f:
                res = subprocess.run([str(counter), out_f.name, args.events,
                                      str(c.exe)], capture_output=True,
                                     text=True, env=run_env, timeout=600)
                stdout = Path(out_f.name).read_text(errors="replace").strip()
            f = res.stdout.split()
            if res.returncode != 0 or len(f) != 5 + len(names):
                sys.exit(f"error: count_events failed: {res.stderr.strip()}")
            ok = int(f[1] == "0" and stdout == c.expected_output)
            rows.append([args.state, args.round, cpus_online, c.compiler,
                         c.program, c.opt, c.flag_id, rep,
                         int(rep < args.warmup), *f[:2], ok, *f[2:]])
        print(f"[smt_stalls] rep {rep + 1}/{args.warmup + args.reps}")
    append_csv(args.out / "stalls.csv", header, rows)
    bad = sum(1 for r in rows if not r[11])
    if bad:
        print(f"[smt_stalls] WARNING: {bad} executions without the expected "
              f"output (output_ok=0)")
    if any(r[12] == "-1.0000" for r in rows):
        print("[smt_stalls] WARNING: counters unavailable "
              "(check perf_event_paranoid and --cap-add PERFMON)")


if __name__ == "__main__":
    main()
