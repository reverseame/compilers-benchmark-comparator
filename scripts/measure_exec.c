/* Minimal measurement wrapper.
 *
 * The campaign driver is a Python process with a large resident set; a child
 * forked from it inherits that peak-RSS accounting, so its ru_maxrss would
 * report the parent's footprint instead of its own. This wrapper is tiny, so
 * forking the benchmark from here gives an honest ru_maxrss (same approach
 * as GNU time and hyperfine).
 *
 * Usage: measure_exec <stdout_file> <cmd> [args...]
 *
 * The benchmark's stdout+stderr are redirected to <stdout_file>. One line is
 * printed to the wrapper's stdout:
 *
 *   wall_s user_s sys_s max_rss_kb exit_code term_signal
 *   minflt majflt vol_cs invol_cs
 *   instructions cycles branch_misses cache_misses
 *   energy_pkg_uj energy_cores_uj
 *
 * The first ten fields come from CLOCK_MONOTONIC and the wait4(2) rusage of
 * the single child execution. The perf fields are user-space hardware
 * counters attached to the child before it execs (so they include process
 * startup, consistently with wall_s); they need perf_event_paranoid <= 2 or
 * CAP_PERFMON and are printed as -1 when unavailable. The energy fields are
 * Intel RAPL deltas (package and core domains) read around the child's
 * lifetime; they need a readable /sys/class/powercap (root) and are -1 when
 * unavailable. Note that RAPL counts the whole package, not just the
 * benchmark's core.
 *
 * Wrapper exit code: 0 on success, 125 on internal failure (127 in the child
 * if exec fails, which surfaces as exit_code=127).
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <linux/perf_event.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int perf_open(uint32_t type, uint64_t config, pid_t pid) {
    struct perf_event_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.size = sizeof(attr);
    attr.type = type;
    attr.config = config;
    attr.disabled = 1;
    attr.inherit = 1;         /* follow the child's own children/threads */
    attr.exclude_kernel = 1;  /* user space only: works at paranoid <= 2 */
    attr.exclude_hv = 1;
    return (int)syscall(SYS_perf_event_open, &attr, pid, -1, -1, 0);
}

static long long perf_read(int fd) {
    uint64_t v;
    if (fd < 0 || read(fd, &v, sizeof(v)) != sizeof(v)) return -1;
    return (long long)v;
}

static long long rapl_read(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    long long v = -1;
    if (fscanf(f, "%lld", &v) != 1) v = -1;
    fclose(f);
    return v;
}

static long long rapl_delta(const char *dir, long long before, long long after) {
    if (before < 0 || after < 0) return -1;
    if (after >= before) return after - before;
    /* the counter wrapped: recover with the domain's range if readable */
    char path[256];
    snprintf(path, sizeof(path), "%s/max_energy_range_uj", dir);
    long long range = rapl_read(path);
    return range > 0 ? after + range - before : -1;
}

/* RAPL domain directories. The canonical sysfs location comes first; the
 * /rapl fallback exists because Docker's sysfs lists /sys/class/powercap
 * entries without materializing their targets, so campaigns bind-mount the
 * host's /sys/devices/virtual/powercap at /rapl instead. */
static char rapl_pkg[64], rapl_cores[64];

static void rapl_locate(void) {
    const char *roots[] = {"/sys/class/powercap", "/rapl"};
    for (unsigned i = 0; i < sizeof(roots) / sizeof(roots[0]); i++) {
        char probe[96];
        snprintf(probe, sizeof(probe), "%s/intel-rapl:0/energy_uj", roots[i]);
        if (access(probe, R_OK) == 0) {
            snprintf(rapl_pkg, sizeof(rapl_pkg), "%s/intel-rapl:0", roots[i]);
            snprintf(rapl_cores, sizeof(rapl_cores), "%s/intel-rapl:0:0", roots[i]);
            return;
        }
    }
    snprintf(rapl_pkg, sizeof(rapl_pkg), "/nonexistent");
    snprintf(rapl_cores, sizeof(rapl_cores), "/nonexistent");
}

static long long rapl_energy(const char *dir) {
    char path[128];
    snprintf(path, sizeof(path), "%s/energy_uj", dir);
    return rapl_read(path);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <stdout_file> <cmd> [args...]\n", argv[0]);
        return 125;
    }
    int fd = open(argv[1], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { perror("open"); return 125; }

    /* the child blocks on this pipe until the counters are attached */
    int gate[2];
    if (pipe(gate) < 0) { perror("pipe"); return 125; }

    rapl_locate();
    long long e_pkg0 = rapl_energy(rapl_pkg);
    long long e_cor0 = rapl_energy(rapl_cores);

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
        execv(argv[2], &argv[2]);
        perror("execv");
        _exit(127);
    }
    close(fd);
    close(gate[0]);

    int pf_ins = perf_open(PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS, pid);
    int pf_cyc = perf_open(PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES, pid);
    int pf_brm = perf_open(PERF_TYPE_HARDWARE, PERF_COUNT_HW_BRANCH_MISSES, pid);
    int pf_cam = perf_open(PERF_TYPE_HARDWARE, PERF_COUNT_HW_CACHE_MISSES, pid);
    int pfds[4] = {pf_ins, pf_cyc, pf_brm, pf_cam};
    for (int i = 0; i < 4; i++)
        if (pfds[i] >= 0) ioctl(pfds[i], PERF_EVENT_IOC_ENABLE, 0);

    /* the wall clock starts when the gate opens: the child execs only after
     * this point, so fork and counter-setup overhead stay out of wall_s */
    clock_gettime(CLOCK_MONOTONIC, &t0);
    if (write(gate[1], "x", 1) != 1) { perror("write"); return 125; }
    close(gate[1]);

    int status;
    struct rusage ru;
    if (wait4(pid, &status, 0, &ru) < 0) { perror("wait4"); return 125; }
    clock_gettime(CLOCK_MONOTONIC, &t1);

    long long e_pkg1 = rapl_energy(rapl_pkg);
    long long e_cor1 = rapl_energy(rapl_cores);

    double wall = (double)(t1.tv_sec - t0.tv_sec) +
                  (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;
    double user = (double)ru.ru_utime.tv_sec + (double)ru.ru_utime.tv_usec / 1e6;
    double sys  = (double)ru.ru_stime.tv_sec + (double)ru.ru_stime.tv_usec / 1e6;
    int exit_code = -1, sig = 0;
    if (WIFEXITED(status)) exit_code = WEXITSTATUS(status);
    else if (WIFSIGNALED(status)) sig = WTERMSIG(status);

    printf("%.9f %.6f %.6f %ld %d %d %ld %ld %ld %ld "
           "%lld %lld %lld %lld %lld %lld\n",
           wall, user, sys, (long)ru.ru_maxrss, exit_code, sig,
           (long)ru.ru_minflt, (long)ru.ru_majflt,
           (long)ru.ru_nvcsw, (long)ru.ru_nivcsw,
           perf_read(pf_ins), perf_read(pf_cyc),
           perf_read(pf_brm), perf_read(pf_cam),
           rapl_delta(rapl_pkg, e_pkg0, e_pkg1),
           rapl_delta(rapl_cores, e_cor0, e_cor1));
    return 0;
}
