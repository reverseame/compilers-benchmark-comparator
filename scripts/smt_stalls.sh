#!/bin/sh
# Host-side driver for scripts/smt_stalls.py: alternates the SMT sibling of
# the measurement CPU between offline and online over several rounds
# (offline, online, offline, online, ...) and runs one container per state,
# so slow drift does not line up with the SMT state.
#
# Run from the repository root, as root (CPU hotplug), after
#   sudo sysctl kernel.perf_event_paranoid=1   (restore it afterwards)
#
#   sudo CPU=3 SIBLING=7 ROUNDS=3 REPS=20 scripts/smt_stalls.sh [image]
#
# image defaults to the digest used in the article. The sibling's original
# state is restored on exit. Results go to results_csv/<timestamp>-smt-stalls/.
set -eu

IMAGE=${1:-ghcr.io/reverseame/compilers-benchmark-comparator@sha256:1840aca51f5ac12438438e429215f8e90f7a1c68d52b5dbf37bffcb6dd049163}
CPU=${CPU:-3}
SIBLING=${SIBLING:-7}
ROUNDS=${ROUNDS:-3}
REPS=${REPS:-20}
ONLINE=/sys/devices/system/cpu/cpu$SIBLING/online

[ "$(id -u)" = 0 ] || { echo "error: run as root (CPU hotplug)" >&2; exit 1; }
[ "$(cat /proc/sys/kernel/perf_event_paranoid)" -le 1 ] || {
    echo "error: set kernel.perf_event_paranoid=1 first" >&2; exit 1; }

orig=$(cat "$ONLINE")
trap 'echo "$orig" > "$ONLINE"' EXIT
echo 1 > "$ONLINE"
grep -qw "$SIBLING" "/sys/devices/system/cpu/cpu$CPU/topology/thread_siblings_list" || {
    echo "error: cpu$SIBLING is not the SMT sibling of cpu$CPU" >&2; exit 1; }

OUT=results_csv/$(date -u +%Y%m%d-%H%M%S)-smt-stalls
mkdir -p "$OUT"
for round in $(seq "$ROUNDS"); do
    for state in offline online; do
        if [ "$state" = offline ]; then echo 0 > "$ONLINE"; else echo 1 > "$ONLINE"; fi
        sleep 5
        docker run --rm --cpuset-cpus="$CPU" --cap-add PERFMON \
            --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
            -v "$PWD/scripts/smt_stalls.py:/app/scripts/smt_stalls.py:ro" \
            -v "$PWD/scripts/count_events.c:/app/scripts/count_events.c:ro" \
            -v "$PWD/config/matrix.yaml:/app/config/matrix.yaml:ro" \
            -v "$PWD/$OUT:/app/out" \
            --entrypoint python3 "$IMAGE" \
            scripts/smt_stalls.py --state "$state" --round "$round" \
            --reps "$REPS" --out /app/out
    done
done
echo "results in $OUT"
