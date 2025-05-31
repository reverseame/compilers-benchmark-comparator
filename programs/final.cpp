#include <iostream>
#include <cstring>    // strcpy, strlen
#include <cstdlib>    // malloc, free

int vulnerable_function(const char* input) {
    char buffer[32];
    strcpy(buffer, input);  // Función fortificable
    return strlen(buffer);
}

int main() {
    // Cadena de prueba (puede exceder el tamaño del buffer)
    const char* test_input = "Esta cadena es un poco más larga de lo habitual";

    // Reserva de memoria dinámica
    char* dynamic_memory = (char*)malloc(100);
    if (!dynamic_memory) return 1;

    for (int i = 0; i < 100; ++i) {
        dynamic_memory[i] = i % 256;
    }

    // Llamada a función vulnerable
    int len = vulnerable_function(test_input);

    std::cout << "Longitud copiada: " << len << "\n";

    free(dynamic_memory);
    return 0;
}

