// sum benchmark: allocates a one-million-element vector, initializes it to a
// constant and computes an indexed reduction ITERS times.
//
// Must stay semantically identical to suma.cpp. Indexed access is used on
// purpose (bounds-checked in Rust, unchecked in C++): that difference is part
// of what the study measures. black_box forces the vector to be re-read on
// every outer iteration.
use std::hint::black_box;

fn main() {
    const N: usize = 1_000_000;
    const ITERS: usize = 200;

    let vec = vec![69i32; N];

    let mut total: i64 = 0;
    for _ in 0..ITERS {
        let mut sum: i64 = 0;
        for i in 0..vec.len() {
            sum += vec[i] as i64;
        }
        total += sum;
        black_box(&vec);
    }

    println!("{}", total); // expected: 13800000000
}
