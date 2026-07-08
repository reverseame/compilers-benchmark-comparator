// copy benchmark: repeatedly copies a 31-byte string into a 32-byte stack
// buffer. Must stay semantically identical to final.cpp: same buffer size,
// same input, same iteration count, input fits the buffer.
//
// copy_from_slice is the idiomatic bounds-checked equivalent of the C strcpy
// (it panics if the lengths do not match, which is the Rust counterpart of
// the C/C++ mitigations firing). black_box keeps the source opaque and the
// buffer live so the loop cannot be optimized away.
use std::hint::black_box;

const TEXT: &str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"; // 31 bytes

fn main() {
    const ITERS: usize = 10_000_000;

    let mut buffer = [0u8; 32];

    let mut total: i64 = 0;
    for _ in 0..ITERS {
        let src = black_box(TEXT.as_bytes()); // opaque source
        buffer[..src.len()].copy_from_slice(src); // bounds-checked copy
        black_box(&buffer);
        // strlen equivalent: position of the first NUL byte.
        total += buffer.iter().position(|&b| b == 0).unwrap_or(32) as i64;
    }

    println!("{}", total); // expected: 310000000
}
