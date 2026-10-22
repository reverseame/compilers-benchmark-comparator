/* count_events.c: per-execution raw hardware counters.
 *
 * Companion to measure_exec.c for experiments that need model-specific
 * events (e.g. Skylake's RESOURCE_STALLS.SB) instead of the four generic
 * counters the campaign records. Same fork/gate/execv/wait4 structure: the
 * counters are attached to the child before it execs and the wall clock
 * starts when the gate opens.
 *
 * Usage: count_events <stdout_file> <events> <cmd> [args...]
 *
 *   <events> is a comma-separated list of name=config pairs, where config
 *   is a raw PERF_TYPE_RAW encoding (umask << 8 | event, plus cmask << 24
 *   if needed), e.g. "sb=0x08a2,any=0x01a2" for RESOURCE_STALLS.SB and
 *   RESOURCE_STALLS.ANY on Skylake. Cycles and instructions are always
 *   counted, as the first two values.
 *
 * All counters form one group, so they are scheduled together and are
 * directly comparable; user space only, like measure_exec.c. One line is
 * printed to stdout:
 *
 *   wall_s exit_code running_ratio cycles instructions <event values...>
 *
 * running_ratio is time_running / time_enabled of the group: 1 means the
 * group was counted the whole time, < 1 that it was multiplexed (values are
 * then not scaled), -1 that the counters are unavailable (every value is
 * -1, as is any single event the PMU rejected).
 *
 * The counters are not inherited (the group read format does not allow it),
 * which is fine for the single-threaded benchmarks of this repository.
 *
 * Wrapper exit code: 0 on success, 125 on internal failure (127 in the child
 * if exec fails, which surfaces as exit_code=127).
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <linux/perf_event.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define MAXEV 8

static int perf_open(uint32_t type, uint64_t config, pid_t pid, int group) {
    struct perf_event_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.size = sizeof(attr);
    attr.type = type;
    attr.config = config;
    attr.disabled = group < 0;  /* only the leader; members follow it */
    attr.exclude_kernel = 1;
    attr.exclude_hv = 1;
    attr.read_format = PERF_FORMAT_GROUP | PERF_FORMAT_TOTAL_TIME_ENABLED |
                       PERF_FORMAT_TOTAL_TIME_RUNNING;
    return (int)syscall(SYS_perf_event_open, &attr, pid, -1, group, 0);
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <stdout_file> <events> <cmd> [args...]\n",
                argv[0]);
        return 125;
    }

    /* cycles, instructions, then the raw events */
    uint32_t types[MAXEV] = {PERF_TYPE_HARDWARE, PERF_TYPE_HARDWARE};
    uint64_t configs[MAXEV] = {PERF_COUNT_HW_CPU_CYCLES,
                               PERF_COUNT_HW_INSTRUCTIONS};
    int nev = 2;
    char *spec = strdup(argv[2]);
    for (char *tok = strtok(spec, ","); tok; tok = strtok(NULL, ",")) {
        char *eq = strchr(tok, '=');
        if (!eq || nev == MAXEV) {
            fprintf(stderr, "bad or too many events: %s\n", argv[2]);
            return 125;
        }
        types[nev] = PERF_TYPE_RAW;
        configs[nev++] = strtoull(eq + 1, NULL, 0);
    }

    int fd = open(argv[1], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { perror("open"); return 125; }
    int gate[2];
    if (pipe(gate) < 0) { perror("pipe"); return 125; }

    struct timespec t0, t1;
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return 125; }
    if (pid == 0) {
        close(gate[1]);
        char go;
        (void)!read(gate[0], &go, 1);
        close(gate[0]);
        dup2(fd, 1);
        dup2(fd, 2);
        close(fd);
        execv(argv[3], &argv[3]);
        perror("execv");
        _exit(127);
    }
    close(fd);
    close(gate[0]);

    /* slot[i] = index of event i in the group read, or -1 if rejected */
    int slot[MAXEV], members = 0;
    int leader = perf_open(types[0], configs[0], pid, -1);
    for (int i = 0; i < nev; i++) {
        int f = i == 0 ? leader
                       : (leader >= 0 ? perf_open(types[i], configs[i], pid,
                                                  leader) : -1);
        slot[i] = f >= 0 ? members++ : -1;
    }
    if (leader >= 0)
        ioctl(leader, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);

    clock_gettime(CLOCK_MONOTONIC, &t0);
    if (write(gate[1], "x", 1) != 1) { perror("write"); return 125; }
    close(gate[1]);

    int status;
    if (waitpid(pid, &status, 0) < 0) { perror("waitpid"); return 125; }
    clock_gettime(CLOCK_MONOTONIC, &t1);

    /* group read: nr, time_enabled, time_running, values[nr] */
    uint64_t buf[3 + MAXEV];
    double ratio = -1;
    if (leader >= 0 && read(leader, buf, sizeof(buf)) > 0 && buf[1] > 0)
        ratio = (double)buf[2] / (double)buf[1];

    double wall = (double)(t1.tv_sec - t0.tv_sec) +
                  (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;
    int exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    printf("%.9f %d %.4f", wall, exit_code, ratio);
    for (int i = 0; i < nev; i++)
        printf(" %lld", ratio < 0 || slot[i] < 0
                            ? -1LL : (long long)buf[3 + slot[i]]);
    printf("\n");
    return 0;
}
