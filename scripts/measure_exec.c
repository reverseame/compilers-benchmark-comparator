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
 *   wall_s user_s sys_s max_rss_kb exit_code term_signal
 * Wrapper exit code: 0 on success, 125 on internal failure (127 in the child
 * if exec fails, which surfaces as exit_code=127).
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <stdout_file> <cmd> [args...]\n", argv[0]);
        return 125;
    }
    int fd = open(argv[1], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { perror("open"); return 125; }

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return 125; }
    if (pid == 0) {
        dup2(fd, 1);
        dup2(fd, 2);
        close(fd);
        execv(argv[2], &argv[2]);
        perror("execv");
        _exit(127);
    }
    close(fd);

    int status;
    struct rusage ru;
    if (wait4(pid, &status, 0, &ru) < 0) { perror("wait4"); return 125; }
    clock_gettime(CLOCK_MONOTONIC, &t1);

    double wall = (double)(t1.tv_sec - t0.tv_sec) +
                  (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;
    double user = (double)ru.ru_utime.tv_sec + (double)ru.ru_utime.tv_usec / 1e6;
    double sys  = (double)ru.ru_stime.tv_sec + (double)ru.ru_stime.tv_usec / 1e6;
    int exit_code = -1, sig = 0;
    if (WIFEXITED(status)) exit_code = WEXITSTATUS(status);
    else if (WIFSIGNALED(status)) sig = WTERMSIG(status);

    printf("%.9f %.6f %.6f %ld %d %d\n",
           wall, user, sys, (long)ru.ru_maxrss, exit_code, sig);
    return 0;
}
