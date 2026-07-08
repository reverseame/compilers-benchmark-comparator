// sum benchmark: allocates a one-million-element vector, initializes it to a
// constant and computes an indexed reduction ITERS times.
//
// Must stay semantically identical to suma.rs. The result is printed so the
// optimizer cannot discard the work, and the asm barrier forces the vector to
// be re-read on every outer iteration (otherwise the whole loop nest folds
// into a constant).
#include <cstdio>
#include <vector>

int main() {
    constexpr std::size_t N = 1000000;
    constexpr int ITERS = 200;

    std::vector<int> vec(N, 69);

    long long total = 0;
    for (int it = 0; it < ITERS; ++it) {
        long long sum = 0;
        for (std::size_t i = 0; i < vec.size(); ++i) {
            sum += vec[i];
        }
        total += sum;
        asm volatile("" : : "g"(vec.data()) : "memory");
    }

    std::printf("%lld\n", total); // expected: 13800000000
    return 0;
}
