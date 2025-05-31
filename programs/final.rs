use std::ffi::CString;
use std::ptr;

fn vulnerable_function(input: &str) -> usize {
    let mut buffer = [0u8; 32];
    // Simula un strcpy: copia byte por byte sin comprobar tamaño
    let bytes = input.as_bytes();
    for i in 0..bytes.len() {
        // Esto puede desbordar si input > 32, útil para ver sanitizadores
        if i < buffer.len() {
            buffer[i] = bytes[i];
        }
    }
    bytes.len()
}

fn main() {
    // Cadena de prueba fija
    let test_input = "Esta cadena es un poco más larga de lo habitual";

    // Reserva de memoria dinámica (heap)
    let mut dynamic_memory = Vec::with_capacity(100);
    for i in 0..100 {
        dynamic_memory.push((i % 256) as u8);
    }

    // Llamada a la función vulnerable
    let len = vulnerable_function(test_input);

    println!("Longitud copiada: {}", len);

    // dynamic_memory se libera automáticamente
}

