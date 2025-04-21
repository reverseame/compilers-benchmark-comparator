#include <cstring>
#include <vector>

void vulnerable_function() {
    char buffer[64];  // <-- Esto activa el stack canary
    std::strcpy(buffer, "Este es un texto de prueba para activar el canario.");
}

int main() {
    vulnerable_function();

    std::vector<int> vec(1000000, 69);
    int sum = 0;
    for (size_t i = 0; i < vec.size(); ++i) {
        sum += vec[i];
    }
    return 0;
}

