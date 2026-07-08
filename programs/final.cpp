// copy benchmark: repeatedly copies a 31-byte string into a 32-byte stack
// buffer with strcpy, the canonical fortifiable libc call.
//
// The input FITS the buffer: this benchmark measures the cost of the
// mitigations (canary setup/check, __strcpy_chk bounds check, sanitizer
// instrumentation) when NO attack fires, which is the cost paid on every
// execution in production. Deliberately-overflowing runs are a separate
// experiment, not this one.
//
// The destination is a plain fixed-size array so __builtin_object_size is
// known and _FORTIFY_SOURCE can instrument the call. The source pointer is
// read through a volatile so the copy cannot be hoisted out of the loop, and
// the asm barrier forces buffer to be treated as modified on every iteration.
#include <cstdio>
#include <cstring>

static const char *const TEXT = "ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"; // 31 chars + NUL

int main() {
    constexpr long ITERS = 10000000;

    const char *volatile src = TEXT; // opaque source: strcpy must really run
    char buffer[32];                 // known-size destination: fortifiable

    long long total = 0;
    for (long i = 0; i < ITERS; ++i) {
        std::strcpy(buffer, src);
        asm volatile("" : : "g"(buffer) : "memory");
        total += std::strlen(buffer);
    }

    std::printf("%lld\n", total); // expected: 310000000
    return 0;
}
