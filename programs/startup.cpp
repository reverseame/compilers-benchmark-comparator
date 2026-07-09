// Empty workload: measures process startup and teardown only (dynamic
// linking, relocation processing, language-runtime initialization). This is
// where the real cost of PIE and full RELRO (-z now, eager binding) is paid;
// the loop benchmarks amortize it away. Companion of startup.rs.
#include <cstdio>

int main() {
    std::puts("ok");
    return 0;
}
