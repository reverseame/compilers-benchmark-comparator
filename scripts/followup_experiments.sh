#!/bin/bash
# Follow-up experiments for the article's revision, to be run on the host of
# the published campaign (Intel Core i7-6700, Debian, kernel 6.1) with the
# same configuration: governor performance, turbo off, the SMT sibling of
# the measurement CPU offline, perf counters and RAPL available, and the
# container image pinned by digest.
#
# Steps (build, rapl, order and smt by default, or any subset given as
# arguments, run in this order):
#   build   isolated, repeated build cost (scripts/build_cost.py)
#   rapl    RAPL / wall-clock window mismatch (scripts/rapl_window_check.c)
#   order   campaign with randomized run order (campaign.py --order random),
#           followed by plot_results.py and paired_stats.py
#   gccopt  supplementary campaign of g++ at -Oz and -Ofast
#           (config/matrix-gcc-oz-ofast.yaml, about 40 min) with the image's
#           own scripts, as in the published campaign, followed by
#           analyze.py and paired_stats.py; only when named
#   full    the complete campaign of config/matrix.yaml (all compilers and
#           levels, including g++ -Oz/-Ofast) with the current campaign.py
#           and measure_exec.c, the order shuffled in every sweep, and the
#           binaries kept, followed by analyze.py, plot_results.py and
#           paired_stats.py; about 6 h; only when named. It refuses to start
#           if the machine is busy and logs the load average every minute
#   smt     store-buffer stalls with the sibling offline and online
#           (scripts/smt_stalls.sh)
#
# Usage, from the repository root on an otherwise idle machine:
#   sudo scripts/followup_experiments.sh                # default steps
#   sudo scripts/followup_experiments.sh rapl smt       # a subset
#   sudo scripts/followup_experiments.sh gccopt         # GCC -Oz/-Ofast
#   sudo scripts/followup_experiments.sh full           # complete campaign
#
# Settings (environment variables, defaults in parentheses):
#   CPU (3), SIBLING (7), IMAGE (the article's digest), BUILD_REPS (10),
#   RAPL_RUNS (300), ORDER_PROGRAMS (startup; empty = full matrix, ~2.5 h),
#   ORDER_REPS (50), GCCOPT_REPS (50), FULL_REPS (50), FULL_ORDER (random),
#   FULL_SEED (20260708), ALLOW_BUSY (0: refuse to start the full campaign
#   if the 1-minute load average exceeds 0.5), SMT_ROUNDS (3), SMT_REPS (20),
#   FORCE (0: refuse to run on a CPU other than the i7-6700).
#
# The host settings changed here (governors, turbo, sibling state,
# perf_event_paranoid) are restored on exit; the intel_rapl_msr module is
# left loaded. Results go to results_csv/ (one directory per step, owned by
# the invoking user) and the full log to results_csv/followup-<ts>.log.
set -euo pipefail

CPU=${CPU:-3}
SIBLING=${SIBLING:-7}
IMAGE=${IMAGE:-ghcr.io/reverseame/compilers-benchmark-comparator@sha256:1840aca51f5ac12438438e429215f8e90f7a1c68d52b5dbf37bffcb6dd049163}
BUILD_REPS=${BUILD_REPS:-10}
RAPL_RUNS=${RAPL_RUNS:-300}
ORDER_PROGRAMS=${ORDER_PROGRAMS-startup}
ORDER_REPS=${ORDER_REPS:-50}
SMT_ROUNDS=${SMT_ROUNDS:-3}
SMT_REPS=${SMT_REPS:-20}
GCCOPT_REPS=${GCCOPT_REPS:-50}
FULL_REPS=${FULL_REPS:-50}
FULL_ORDER=${FULL_ORDER:-random}
FULL_SEED=${FULL_SEED:-20260708}
ALLOW_BUSY=${ALLOW_BUSY:-0}
FORCE=${FORCE:-0}
STEPS=${*:-build rapl order smt}

SYS=/sys/devices/system/cpu
ONLINE=$SYS/cpu$SIBLING/online
NO_TURBO=$SYS/intel_pstate/no_turbo
PARANOID=/proc/sys/kernel/perf_event_paranoid
TS=$(date -u +%Y%m%d-%H%M%S)

die() { echo "error: $*" >&2; exit 1; }
log() { echo "[followup $(date -u +%H:%M:%S)] $*"; }
as_user() {   # post-processing and git run as the invoking user
    if [ -n "${SUDO_USER:-}" ]; then sudo -u "$SUDO_USER" -H "$@"; else "$@"; fi
}
has_step() { case " $STEPS " in *" $1 "*) return 0 ;; esac; return 1; }

# ---- preflight ------------------------------------------------------------
[ "$(id -u)" = 0 ] || die "run as root (sudo): CPU hotplug and sysctl"
[ -f scripts/campaign.py ] && [ -f config/matrix.yaml ] \
    || die "run from the repository root"
command -v docker >/dev/null || die "docker not found"
for s in $STEPS; do
    case $s in build|rapl|order|gccopt|full|smt) ;; *) die "unknown step: $s" ;; esac
done
if ! grep -q "i7-6700 " /proc/cpuinfo && [ "$FORCE" != 1 ]; then
    die "this is not the i7-6700 of the campaign (FORCE=1 to run anyway)"
fi

mkdir -p results_csv
before=$(ls results_csv)   # anything else under results_csv is new
LOG=results_csv/followup-$TS.log
exec > >(tee -a "$LOG") 2>&1
log "steps: $STEPS"

# ---- save and restore the host state --------------------------------------
orig_online=$(cat "$ONLINE")
orig_no_turbo=$(cat "$NO_TURBO" 2>/dev/null || echo "")
orig_paranoid=$(cat "$PARANOID")
echo 1 > "$ONLINE"   # online, so its governor can be set and checked
declare -A orig_gov
for g in $SYS/cpu[0-9]*/cpufreq/scaling_governor; do orig_gov[$g]=$(cat "$g"); done

restore() {
    set +e
    [ -n "${loadmon:-}" ] && kill "$loadmon" 2>/dev/null
    echo 1 > "$ONLINE"
    for g in "${!orig_gov[@]}"; do echo "${orig_gov[$g]}" > "$g"; done
    echo "$orig_online" > "$ONLINE"
    [ -n "$orig_no_turbo" ] && echo "$orig_no_turbo" > "$NO_TURBO"
    echo "$orig_paranoid" > "$PARANOID"
    # hand the new results over to the invoking user
    if [ -n "${SUDO_UID:-}" ]; then
        for d in $(ls results_csv); do
            echo "$before" | grep -qx "$d" \
                || chown -R "$SUDO_UID:$SUDO_GID" "results_csv/$d"
        done
    fi
    log "host settings restored"
}
trap restore EXIT

grep -qw "$SIBLING" "$SYS/cpu$CPU/topology/thread_siblings_list" \
    || die "cpu$SIBLING is not the SMT sibling of cpu$CPU"

# ---- campaign configuration -----------------------------------------------
for g in "${!orig_gov[@]}"; do echo performance > "$g"; done
[ -n "$orig_no_turbo" ] && echo 1 > "$NO_TURBO"
echo 1 > "$PARANOID"
modprobe intel_rapl_msr
echo 0 > "$ONLINE"
sleep 5
log "governor=$(cat $SYS/cpu$CPU/cpufreq/scaling_governor)" \
    "no_turbo=$(cat "$NO_TURBO" 2>/dev/null || echo n/a)" \
    "cpus_online=$(cat $SYS/online) perf_event_paranoid=$(cat $PARANOID)"
read -r load1 _ < /proc/loadavg
log "load average (1 min): $load1"
awk -v l="$load1" 'BEGIN { exit !(l > 0.5) }' \
    && log "WARNING: the machine does not look idle" \
    && ps -eo user,pid,pcpu,etime,comm --sort=-pcpu | head -6
if has_step full && [ "$ALLOW_BUSY" != 1 ] \
    && awk -v l="$load1" 'BEGIN { exit !(l > 0.5) }'; then
    die "full: the machine is busy (load $load1); other processes share the L3 cache and memory bandwidth and can migrate to cpu$CPU. Wait until it is idle, or set ALLOW_BUSY=1"
fi

log "pulling $IMAGE"
docker pull -q "$IMAGE"

{
    echo "date_utc: $TS"
    echo "steps: $STEPS"
    echo "uname: $(uname -a)"
    echo "cpu_model: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2-)"
    echo "governor: $(cat $SYS/cpu$CPU/cpufreq/scaling_governor)"
    echo "no_turbo: $(cat "$NO_TURBO" 2>/dev/null || echo n/a)"
    echo "cpus_online: $(cat $SYS/online)"
    echo "perf_event_paranoid: $(cat $PARANOID)"
    echo "docker: $(docker version --format '{{.Server.Version}}')"
    echo "image: $IMAGE"
    echo "repo_commit: $(as_user git rev-parse HEAD)"
    echo "repo_dirty: $(as_user git status --short | wc -l) files"
    echo "settings: CPU=$CPU SIBLING=$SIBLING BUILD_REPS=$BUILD_REPS" \
         "RAPL_RUNS=$RAPL_RUNS ORDER_PROGRAMS=$ORDER_PROGRAMS" \
         "ORDER_REPS=$ORDER_REPS GCCOPT_REPS=$GCCOPT_REPS FULL_REPS=$FULL_REPS" \
         "FULL_ORDER=$FULL_ORDER FULL_SEED=$FULL_SEED" \
         "SMT_ROUNDS=$SMT_ROUNDS SMT_REPS=$SMT_REPS"
} > "results_csv/followup-$TS-host.txt"

# Same container options as the published campaign. The image's built-in
# config/matrix.yaml predates the campaign's (it lacks Rustc's
# stack_protector_all), so the repository's matrix is mounted over it.
DOCKER=(docker run --rm --cpuset-cpus="$CPU" --cap-add PERFMON
        --security-opt seccomp=unconfined --security-opt apparmor=unconfined
        -v /sys/devices/virtual/powercap:/rapl:ro
        -v "$PWD/config/matrix.yaml:/app/config/matrix.yaml:ro")

# ---- 1. build cost --------------------------------------------------------
if has_step build; then
    log "build: build_cost.py, sum -O3, $BUILD_REPS reps"
    "${DOCKER[@]}" --entrypoint python3 \
        -v "$PWD/scripts/build_cost.py:/app/scripts/build_cost.py:ro" \
        -v "$PWD/results_csv:/app/results_csv" \
        "$IMAGE" scripts/build_cost.py --matrix config/matrix.yaml \
        --programs suma --reps "$BUILD_REPS"
fi

# ---- 2. RAPL window -------------------------------------------------------
if has_step rapl; then
    out=results_csv/$TS-rapl-window
    mkdir -p "$out"
    log "rapl: $RAPL_RUNS runs of startup (g++ -O3) -> $out"
    "${DOCKER[@]}" --entrypoint sh \
        -v "$PWD/scripts/rapl_window_check.c:/tmp/m.c:ro" \
        -v "$PWD/$out:/out" \
        "$IMAGE" -c "
        gcc -O2 /tmp/m.c -o /tmp/m && g++ -O3 programs/startup.cpp -o /tmp/s &&
        for i in \$(seq 10); do /tmp/m /dev/null /tmp/s >/dev/null 2>&1; done &&
        for i in \$(seq $RAPL_RUNS); do
            /tmp/m /dev/null /tmp/s 2>>/out/window.txt >>/out/measure.txt
        done"
    # pre_us/post_us summary; measure.txt shows whether perf and RAPL were on
    python3 -I - "$out" <<'EOF' | tee "$out/summary.txt"
import statistics, sys
from pathlib import Path
d = Path(sys.argv[1])
pre, post = [], []
for line in (d / "window.txt").read_text().split("\n"):
    f = line.split()
    if len(f) == 4 and f[0] == "pre_us":
        pre.append(float(f[1])); post.append(float(f[3]))
m = [l.split() for l in (d / "measure.txt").read_text().splitlines()]
perf = sum(f[10] != "-1" for f in m)
rapl = sum(f[14] != "-1" for f in m)
q = lambda v, p: sorted(v)[min(int(p * len(v)), len(v) - 1)]
tot = [a + b for a, b in zip(pre, post)]
print(f"runs: {len(pre)} (perf counters on in {perf}, RAPL on in {rapl})")
for name, v in (("pre_us", pre), ("post_us", post), ("total_us", tot)):
    print(f"{name:9s} median {statistics.median(v):7.1f}  "
          f"p95 {q(v, 0.95):7.1f}")
if perf < len(m) or rapl < len(m):
    print("WARNING: perf or RAPL unavailable in some runs; the window is "
          "then underestimated and not comparable with the campaign")
EOF
fi

# ---- 3. randomized run order ----------------------------------------------
order_dir=""
if has_step order; then
    progs=()
    [ -n "$ORDER_PROGRAMS" ] && progs=(--programs "$ORDER_PROGRAMS")
    log "order: campaign --order random, programs=${ORDER_PROGRAMS:-all}," \
        "$ORDER_REPS reps"
    "${DOCKER[@]}" \
        -v "$PWD/scripts/campaign.py:/app/scripts/campaign.py:ro" \
        -v "$PWD/scripts/measure_exec.c:/app/scripts/measure_exec.c:ro" \
        -v "$PWD/results_csv:/app/results_csv" \
        "$IMAGE" --matrix config/matrix.yaml "${progs[@]}" \
        --reps "$ORDER_REPS" --order random | tee "results_csv/.order-$TS"
    order_dir=$(sed -n 's/.*Results in results_csv\/\([^ ]*\).*/\1/p' \
        "results_csv/.order-$TS" | tail -1)
    rm -f "results_csv/.order-$TS"
    [ -n "$order_dir" ] || die "order: cannot find the campaign directory"
    log "order: results in results_csv/$order_dir"
fi

# ---- 4. g++ at -Oz and -Ofast ---------------------------------------------
# The image's own campaign.py and measure_exec.c, as in the published
# campaign, so the numbers are comparable with it; only the matrix is mounted.
gccopt_dir=""
if has_step gccopt; then
    log "gccopt: g++ -Oz/-Ofast, all programs, $GCCOPT_REPS reps"
    "${DOCKER[@]}" \
        -v "$PWD/config/matrix-gcc-oz-ofast.yaml:/app/config/matrix-gcc-oz-ofast.yaml:ro" \
        -v "$PWD/results_csv:/app/results_csv" \
        "$IMAGE" --matrix config/matrix-gcc-oz-ofast.yaml \
        --reps "$GCCOPT_REPS" --keep-binaries | tee "results_csv/.gccopt-$TS"
    gccopt_dir=$(sed -n 's/.*Results in results_csv\/\([^ ]*\).*/\1/p' \
        "results_csv/.gccopt-$TS" | tail -1)
    rm -f "results_csv/.gccopt-$TS"
    [ -n "$gccopt_dir" ] || die "gccopt: cannot find the campaign directory"
    log "gccopt: results in results_csv/$gccopt_dir"
fi

# ---- 5. complete campaign -------------------------------------------------
# Current campaign.py (--order, position column) and measure_exec.c (RAPL
# read at the same points as the wall clock) mounted over the image's; the
# toolchains are the image's. The load average is logged every minute.
full_dir=""
if has_step full; then
    log "full: complete matrix, order=$FULL_ORDER seed=$FULL_SEED," \
        "$FULL_REPS reps"
    LOADLOG=results_csv/followup-$TS-load.txt
    ( while sleep 60; do
        echo "$(date -u +%FT%TZ) $(cut -d' ' -f1-3 /proc/loadavg)"
      done ) > "$LOADLOG" &
    loadmon=$!
    "${DOCKER[@]}" \
        -v "$PWD/scripts/campaign.py:/app/scripts/campaign.py:ro" \
        -v "$PWD/scripts/measure_exec.c:/app/scripts/measure_exec.c:ro" \
        -v "$PWD/results_csv:/app/results_csv" \
        "$IMAGE" --matrix config/matrix.yaml --reps "$FULL_REPS" \
        --order "$FULL_ORDER" --seed "$FULL_SEED" --keep-binaries \
        | tee "results_csv/.full-$TS"
    kill "$loadmon" 2>/dev/null || true
    full_dir=$(sed -n 's/.*Results in results_csv\/\([^ ]*\).*/\1/p' \
        "results_csv/.full-$TS" | tail -1)
    rm -f "results_csv/.full-$TS"
    [ -n "$full_dir" ] || die "full: cannot find the campaign directory"
    log "full: results in results_csv/$full_dir; load log in $LOADLOG"
    log "full: highest 1-minute load during the run:" \
        "$(sort -k2 -g "$LOADLOG" | tail -1)"
fi

# ---- 6. SMT store-buffer stalls -------------------------------------------
if has_step smt; then
    log "smt: $SMT_ROUNDS rounds x (offline, online), $SMT_REPS reps"
    CPU=$CPU SIBLING=$SIBLING ROUNDS=$SMT_ROUNDS REPS=$SMT_REPS \
        scripts/smt_stalls.sh "$IMAGE"
    echo 0 > "$ONLINE"   # smt_stalls.sh restores it already; be explicit
fi

# ---- post-processing (as the invoking user, after the timed work) ---------
restore
trap - EXIT
if [ -n "$order_dir$gccopt_dir$full_dir" ]; then
    if as_user python3 -c "import matplotlib" 2>/dev/null; then
        if [ -n "$order_dir" ]; then
            log "order: plot_results.py and paired_stats.py"
            as_user python3 scripts/plot_results.py "results_csv/$order_dir" >/dev/null
            as_user python3 scripts/paired_stats.py "results_csv/$order_dir" \
                | sed -n '/== A\/A control/,$p'
        fi
        if [ -n "$gccopt_dir" ]; then
            # The figures of plot_results.py are drawn at -O3, which this
            # campaign does not have, so only the tables and the paired
            # statistics are produced; failures here do not lose the data.
            log "gccopt: analyze.py and paired_stats.py"
            as_user python3 scripts/analyze.py "results_csv/$gccopt_dir" >/dev/null \
                || log "gccopt: analyze.py failed"
            as_user python3 scripts/paired_stats.py "results_csv/$gccopt_dir" >/dev/null \
                || log "gccopt: paired_stats.py failed"
        fi
        if [ -n "$full_dir" ]; then
            log "full: analyze.py, plot_results.py and paired_stats.py"
            for s in analyze.py plot_results.py paired_stats.py; do
                as_user python3 "scripts/$s" "results_csv/$full_dir" >/dev/null \
                    || log "full: $s failed"
            done
        fi
    else
        log "matplotlib not available; for each new campaign directory, run:"
        log "  pip3 install -r requirements.txt"
        log "  python3 scripts/analyze.py results_csv/<dir>"
        log "  python3 scripts/plot_results.py results_csv/<dir>"
        log "  python3 scripts/paired_stats.py results_csv/<dir>"
    fi
fi

log "done. New result directories:"
for d in $(ls results_csv); do
    echo "$before" | grep -qx "$d" || echo "  results_csv/$d"
done
