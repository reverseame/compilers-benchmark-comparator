#!/usr/bin/env python3
"""Measurement campaign driver.

Replaces the per-compiler shell scripts with a single orchestrator that:

  * reads the experimental matrix from a YAML file (compilers x optimization
    levels x security flags x programs);
  * compiles every cell (in parallel: compilation does not affect timing);
  * runs every binary serially, N repetitions plus a warmup sweep, recording
    EVERY repetition individually (no aggregation) together with its exit
    status, so failed executions can never masquerade as measurements;
  * measures wall time (CLOCK_MONOTONIC), user/sys CPU time and peak RSS of
    the child itself via wait4(2) in a single execution (no double run);
  * records binary properties once per cell: size, stripped size, checksec
    fields (RELRO, canary, NX, PIE, fortified/fortifiable counts), sha256 and
    the exact compiler invocation;
  * captures the execution environment (CPU, kernel, governor, turbo, glibc,
    compiler versions, container limits) for the paper's setup section;
  * writes plain CSV: runs.csv (one row per execution), binaries.csv (one row
    per cell), environment.txt.

Usage:
  python3 scripts/campaign.py --matrix config/matrix.yaml [--reps 10]
      [--programs suma,final] [--compilers g++,clang++,rustc]
      [--out results_csv] [--cpu N] [--keep-binaries]
"""

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# --------------------------------------------------------------------------
# Matrix loading
# --------------------------------------------------------------------------

@dataclass
class Cell:
    compiler: str
    program: str
    opt: str
    flag_id: str
    sec_flags: str
    command: str = ""
    exe: Path = None
    compile_ok: bool = False
    compile_stderr: str = ""
    expected_output: str = ""
    # compile cost (wall is measured under parallel compilation, so
    # user+sys is the contention-robust figure)
    compile_wall_s: float = 0.0
    compile_user_s: float = 0.0
    compile_sys_s: float = 0.0
    compile_max_rss_kb: int = 0
    # binary properties
    size_bytes: int = 0
    size_stripped: int = 0
    sha256: str = ""
    checksec: dict = field(default_factory=dict)


def load_cells(matrix, programs_filter, compilers_filter, src_dir):
    cells = []
    for comp_name, comp in matrix["compilers"].items():
        if compilers_filter and comp_name not in compilers_filter:
            continue
        for prog_name, prog in matrix["programs"].items():
            if programs_filter and prog_name not in programs_filter:
                continue
            src = src_dir / f"{prog_name}.{comp['source_ext']}"
            if not src.exists():
                sys.exit(f"error: source not found: {src}")
            for opt in comp["opt_levels"]:
                for flag_id, sec in comp["security_flags"].items():
                    cells.append(Cell(
                        compiler=comp_name, program=prog_name, opt=opt,
                        flag_id=flag_id, sec_flags=sec,
                        expected_output=str(prog.get("expected_output", "")),
                    ))
    return cells


# --------------------------------------------------------------------------
# Compilation (parallel; happens before any timing)
# --------------------------------------------------------------------------

def _run_with_rusage(cmd, timeout):
    """Run cmd, returning (exited_zero, stderr_tail, wall_s, rusage or None).

    Uses os.wait4 instead of subprocess.run so the child's own CPU time and
    peak RSS are available (per child, which subprocess cannot report)."""
    with tempfile.NamedTemporaryFile() as errf:
        t0 = time.monotonic()
        p = subprocess.Popen(cmd, stdout=errf, stderr=errf)
        deadline = t0 + timeout
        while True:
            pid, status, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() > deadline:
                p.kill()
                deadline = float("inf")  # keep looping until reaped
            time.sleep(0.02)
        p.returncode = 0  # reaped by wait4; silence Popen's destructor
        wall = time.monotonic() - t0
        stderr = Path(errf.name).read_text(errors="replace")
    ok = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
    return ok, stderr, wall, ru


def compile_cell(cell, matrix, src_dir, bin_dir):
    comp = matrix["compilers"][cell.compiler]
    src = src_dir / f"{cell.program}.{comp['source_ext']}"
    safe = lambda s: "".join(c if c.isalnum() else "_" for c in s).strip("_")
    exe = bin_dir / f"{cell.compiler}__{cell.program}__{safe(cell.opt)}__{cell.flag_id}"
    cmd = comp["command"].format(src=str(src), opt=cell.opt,
                                 flags=cell.sec_flags, out=str(exe))
    cell.command = " ".join(cmd.split())
    cell.exe = exe
    ok, stderr, wall, ru = _run_with_rusage(shlex.split(cell.command), 600)
    cell.compile_stderr = stderr.strip()[-500:]
    cell.compile_ok = ok and exe.exists()
    cell.compile_wall_s = round(wall, 3)
    if ru is not None:
        cell.compile_user_s = round(ru.ru_utime, 3)
        cell.compile_sys_s = round(ru.ru_stime, 3)
        cell.compile_max_rss_kb = ru.ru_maxrss  # KB on Linux
    if cell.compile_ok:
        inspect_binary(cell)
    return cell


def inspect_binary(cell):
    exe = cell.exe
    cell.size_bytes = exe.stat().st_size
    cell.sha256 = hashlib.sha256(exe.read_bytes()).hexdigest()
    # stripped size, measured on a copy
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
    try:
        shutil.copy2(exe, tmp_path)
        subprocess.run(["strip", tmp_path], capture_output=True)
        cell.size_stripped = os.path.getsize(tmp_path)
    finally:
        os.unlink(tmp_path)
    # checksec
    try:
        res = subprocess.run(["checksec", "--output=json", f"--file={exe}"],
                             capture_output=True, text=True, timeout=60)
        data = json.loads(res.stdout)
        cell.checksec = data.get(str(exe), next(iter(data.values()), {}))
    except Exception as e:  # checksec failure must not kill the campaign
        cell.checksec = {"error": str(e)[:100]}


# --------------------------------------------------------------------------
# Measured execution. A minimal C wrapper (scripts/measure_exec.c) forks and
# waits for the benchmark and reports wall time (CLOCK_MONOTONIC), user/sys
# CPU time, peak RSS and exit status of that single execution. The wrapper
# exists because a child forked directly from this (large) Python process
# would inherit its peak-RSS accounting and report a bogus max_rss.
# --------------------------------------------------------------------------

def build_wrapper(root):
    src = root / "scripts" / "measure_exec.c"
    out = Path(tempfile.gettempdir()) / "measure_exec"
    cc = next((c for c in ("cc", "gcc", "clang") if shutil.which(c)), None)
    if cc is None:
        sys.exit("error: no C compiler found to build measure_exec")
    res = subprocess.run([cc, "-O2", str(src), "-o", str(out)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"error: cannot build measure_exec:\n{res.stderr}")
    return out


# Extra per-execution fields reported by the wrapper. The perf counters and
# RAPL energy deltas are -1 when the host cannot provide them; those become
# empty CSV cells so downstream tools can tell "unavailable" from zero.
EXTRA_FIELDS = ["min_flt", "maj_flt", "vol_cs", "invol_cs",
                "instructions", "cycles", "branch_misses", "cache_misses",
                "energy_pkg_uj", "energy_cores_uj"]


def run_once(cell, wrapper):
    """Run the binary once; returns a dict with the raw measurements."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    fail = {"wall_s": 0.0, "user_s": 0.0, "sys_s": 0.0, "max_rss_kb": 0,
            "exit_code": -1, "term_signal": "", "output_ok": 0,
            **{k: "" for k in EXTRA_FIELDS}}
    with tempfile.NamedTemporaryFile() as out_f:
        try:
            res = subprocess.run([str(wrapper), out_f.name, str(cell.exe)],
                                 capture_output=True, text=True, env=env,
                                 timeout=600)
        except subprocess.TimeoutExpired:
            return {**fail, "spawn_error": "timeout"}
        if res.returncode != 0:
            return {**fail, "spawn_error": f"wrapper: {res.stderr.strip()[:100]}"}
        stdout = Path(out_f.name).read_text(errors="replace").strip()
    fields = res.stdout.split()
    if len(fields) != 6 + len(EXTRA_FIELDS):
        return {**fail, "spawn_error": f"unparseable: {res.stdout[:100]}"}
    wall, user, sys_t, rss, exit_code, sig = fields[:6]
    extras = [int(x) for x in fields[6:]]
    exit_code, sig = int(exit_code), int(sig)
    output_ok = int(exit_code == 0 and stdout == cell.expected_output)
    return {"wall_s": round(float(wall), 6),
            "user_s": float(user), "sys_s": float(sys_t),
            "max_rss_kb": int(rss),   # KB on Linux
            "exit_code": exit_code if exit_code >= 0 else "",
            "term_signal": sig if sig else "",
            "output_ok": output_ok, "spawn_error": "",
            **{k: (v if v >= 0 else "")
               for k, v in zip(EXTRA_FIELDS, extras)}}


# --------------------------------------------------------------------------
# Environment capture
# --------------------------------------------------------------------------

def read_first(path):
    try:
        return Path(path).read_text().strip().splitlines()[0]
    except Exception:
        return "unavailable"


def capture_environment(args):
    lines = []
    add = lines.append
    add(f"date_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    add(f"uname: {' '.join(os.uname())}")
    add(f"in_container: {os.path.exists('/.dockerenv')}")
    for k in ("PRETTY_NAME",):
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith(k):
                add(f"os_release: {line.split('=',1)[1].strip(chr(34))}")
    model = ""
    try:
        names = [l.split(":", 1)[1].strip()
                 for l in Path("/proc/cpuinfo").read_text().splitlines()
                 if l.lower().startswith(("model name", "hardware"))]
        model = names[0] if names else ""
    except Exception:
        pass
    if not model:  # ARM /proc/cpuinfo often lacks a model name; ask lscpu
        try:
            model = [l.split(":", 1)[1].strip() for l in
                     subprocess.run(["lscpu"], capture_output=True, text=True,
                                    timeout=30).stdout.splitlines()
                     if l.startswith("Model name")][0]
        except Exception:
            model = "unavailable"
    add(f"cpu_model: {model}")
    add(f"nproc: {os.cpu_count()}")
    add(f"cpu_affinity: {sorted(os.sched_getaffinity(0))}")
    add(f"governor: {read_first('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')}")
    add(f"intel_no_turbo: {read_first('/sys/devices/system/cpu/intel_pstate/no_turbo')}")
    # SMT state matters beyond scheduling noise: we have measured ~2.8x
    # runtime differences on a strcpy-bound benchmark depending solely on
    # whether the pinned core's sibling thread was online, with glibc's
    # dispatch verified identical in both states (the core appears to keep
    # its execution resources statically partitioned when the sibling is
    # hot-unplugged).
    add(f"smt_control: {read_first('/sys/devices/system/cpu/smt/control')}")
    add(f"cpus_online: {read_first('/sys/devices/system/cpu/online')}")
    # Availability of the optional per-execution measurements
    add(f"perf_event_paranoid: {read_first('/proc/sys/kernel/perf_event_paranoid')}")
    # /rapl is where campaigns bind-mount the host's powercap tree, since
    # Docker's sysfs does not materialize /sys/class/powercap targets.
    rapl_ok = any(os.access(p, os.R_OK) for p in
                  ("/sys/class/powercap/intel-rapl:0/energy_uj",
                   "/rapl/intel-rapl:0/energy_uj",
                   "/rapl/intel-rapl/intel-rapl:0/energy_uj"))
    add(f"rapl_energy: {'readable' if rapl_ok else 'unavailable'}")
    add(f"boost: {read_first('/sys/devices/system/cpu/cpufreq/boost')}")
    add(f"cgroup_cpu_max: {read_first('/sys/fs/cgroup/cpu.max')}")
    try:
        mem = [l for l in Path("/proc/meminfo").read_text().splitlines()
               if l.startswith("MemTotal")][0]
        add(f"meminfo: {mem}")
    except Exception:
        pass
    for cmd in (["getconf", "GNU_LIBC_VERSION"], ["g++", "--version"],
                ["clang++", "--version"], ["rustc", "--version"],
                ["checksec", "--version"], ["python3", "--version"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=30).stdout.strip().splitlines()
            add(f"{cmd[0]}{'_'+cmd[1] if cmd[0]=='getconf' else ''}: "
                f"{out[0] if out else 'unavailable'}")
        except Exception:
            add(f"{cmd[0]}: unavailable")
    # Exact C-library build. "glibc 2.41" is not enough: benchmarks whose hot
    # loop runs inside libc (strcpy/memcpy/printf) can change speed by
    # integer factors between two package builds of the same glibc version,
    # so record the Debian package revision and the hash of the shared object.
    try:
        pkg = subprocess.run(["dpkg-query", "-W", "libc6"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
        add(f"libc6_package: {pkg or 'unavailable'}")
    except Exception:
        add("libc6_package: unavailable")
    try:
        libc = subprocess.run(
            ["sh", "-c", "sha256sum $(ldconfig -p | awk '/libc.so.6 /{print $NF; exit}')"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        add(f"libc_so_sha256: {libc or 'unavailable'}")
    except Exception:
        add("libc_so_sha256: unavailable")
    add(f"campaign_args: {vars(args)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matrix", default="config/matrix.yaml")
    ap.add_argument("--reps", type=int, default=None,
                    help="timed repetitions per binary (default: matrix value)")
    ap.add_argument("--programs", default="", help="comma-separated subset")
    ap.add_argument("--compilers", default="", help="comma-separated subset")
    ap.add_argument("--out", default="results_csv")
    ap.add_argument("--cpu", type=int, default=None,
                    help="pin the campaign (and children) to this CPU")
    ap.add_argument("--keep-binaries", action="store_true",
                    help="keep compiled binaries under the results directory")
    args = ap.parse_args()

    # Progress must be visible under `docker run`/`docker logs`, where stdout
    # is a pipe and Python would otherwise block-buffer it.
    sys.stdout.reconfigure(line_buffering=True)

    if args.cpu is not None:
        os.sched_setaffinity(0, {args.cpu})

    matrix = yaml.safe_load(Path(args.matrix).read_text())
    reps = args.reps or matrix.get("defaults", {}).get("reps", 10)
    warmups = matrix.get("defaults", {}).get("warmup", 1)

    root = Path(__file__).resolve().parent.parent
    src_dir = root / "programs"
    out_dir = Path(args.out) / time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out_dir.mkdir(parents=True, exist_ok=True)
    bin_dir = (out_dir / "bin") if args.keep_binaries else Path(tempfile.mkdtemp())
    bin_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "environment.txt").write_text(capture_environment(args))
    shutil.copy2(args.matrix, out_dir / "matrix.yaml")
    wrapper = build_wrapper(root)

    cells = load_cells(matrix,
                       set(filter(None, args.programs.split(","))),
                       set(filter(None, args.compilers.split(","))),
                       src_dir)
    print(f"[campaign] {len(cells)} cells, {warmups} warmup + {reps} timed reps each")

    # ---- Phase 1: compile everything in parallel -------------------------
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count()) as pool:
        cells = list(pool.map(
            lambda c: compile_cell(c, matrix, src_dir, bin_dir), cells))
    failed = [c for c in cells if not c.compile_ok]
    print(f"[campaign] compiled {len(cells)-len(failed)}/{len(cells)} cells "
          f"in {time.monotonic()-t0:.0f}s; {len(failed)} compile failures")
    for c in failed:
        print(f"  COMPILE FAIL {c.compiler} {c.program} {c.opt} {c.flag_id}: "
              f"{c.compile_stderr.splitlines()[-1] if c.compile_stderr else '?'}")

    # ---- binaries.csv -----------------------------------------------------
    cs_get = lambda c, k: str(c.checksec.get(k, ""))
    with open(out_dir / "binaries.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["compiler", "program", "opt", "flag_id", "sec_flags",
                    "compile_cmd", "compile_ok", "compile_wall_s",
                    "compile_user_s", "compile_sys_s", "compile_max_rss_kb",
                    "size_bytes", "size_stripped_bytes", "relro", "canary",
                    "nx", "pie", "fortified", "fortifiable", "sha256",
                    "compile_stderr_tail"])
        for c in cells:
            w.writerow([c.compiler, c.program, c.opt, c.flag_id, c.sec_flags,
                        c.command, int(c.compile_ok), c.compile_wall_s,
                        c.compile_user_s, c.compile_sys_s, c.compile_max_rss_kb,
                        c.size_bytes,
                        c.size_stripped, cs_get(c, "relro"), cs_get(c, "canary"),
                        cs_get(c, "nx"), cs_get(c, "pie"), cs_get(c, "fortified"),
                        cs_get(c, "fortify-able") or cs_get(c, "fortifiable"),
                        c.sha256, c.compile_stderr.replace("\n", " | ")])

    # ---- Phase 2: serial measurement, sweep-major order -------------------
    runnable = [c for c in cells if c.compile_ok]
    runs_path = out_dir / "runs.csv"
    bad_runs = 0
    with open(runs_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["compiler", "program", "opt", "flag_id", "sweep",
                    "is_warmup", "wall_s", "user_s", "sys_s", "max_rss_kb",
                    "exit_code", "term_signal", "output_ok",
                    *EXTRA_FIELDS, "epoch_s", "error"])
        total_sweeps = warmups + reps
        for sweep in range(total_sweeps):
            is_warmup = int(sweep < warmups)
            label = "warmup" if is_warmup else f"rep {sweep - warmups + 1}/{reps}"
            print(f"[campaign] sweep {sweep + 1}/{total_sweeps} ({label})")
            for c in runnable:
                m = run_once(c, wrapper)
                if not is_warmup and not m["output_ok"]:
                    bad_runs += 1
                w.writerow([c.compiler, c.program, c.opt, c.flag_id, sweep,
                            is_warmup, m["wall_s"], m["user_s"], m["sys_s"],
                            m["max_rss_kb"], m["exit_code"], m["term_signal"],
                            m["output_ok"],
                            *[m[k] for k in EXTRA_FIELDS],
                            int(time.time()), m.get("spawn_error", "")])
                f.flush()

    print(f"[campaign] done. Results in {out_dir}")
    if failed:
        print(f"[campaign] WARNING: {len(failed)} cells failed to compile "
              f"(see binaries.csv, compile_ok=0)")
    if bad_runs:
        print(f"[campaign] WARNING: {bad_runs} timed executions did not exit 0 "
              f"with the expected output (see runs.csv, output_ok=0)")
    else:
        print("[campaign] all timed executions exited 0 with expected output")
    if not args.keep_binaries:
        shutil.rmtree(bin_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
