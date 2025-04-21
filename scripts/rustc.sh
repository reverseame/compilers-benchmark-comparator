#!/bin/bash
# Script modificado para probar cada nivel de optimización con una opción de seguridad a la vez en rustc

# Se usará Rust Nightly para las compilaciones

# Verificar si se proporcionó un archivo fuente como argumento
if [ "$#" -ne 1 ]; then
    echo "Uso: $0 <archivo_fuente.rs>"
    exit 1
fi

SOURCE="$1"
if [ ! -f "$SOURCE" ]; then
    echo "Error: El archivo fuente '$SOURCE' no existe."
    exit 1
fi

# Colores
BLUE='\033[0;34m'  # Azul
NC='\033[0m'       # Sin color (restablecer)

# Directorio para guardar ejecutables e informe
OUTPUT_DIR="./results_rustc"
mkdir -p "$OUTPUT_DIR"
EXECUTABLES_DIR="${OUTPUT_DIR}/executables"
mkdir -p "$EXECUTABLES_DIR"

REPORT_FILE="${OUTPUT_DIR}/Informe.txt"
REPORT_JSON="${OUTPUT_DIR}/Informe.json"
{
  echo "Informe de rendimiento y seguridad"
  echo "==========================================="
} > "$REPORT_FILE"

# Inicializamos el JSON
echo '{"resultados": []}' > "$REPORT_JSON"

# Función para agregar un resultado al archivo JSON
add_to_json() {
    local json_result="$1"
    # Usar un descriptor de archivo para el bloqueo sobre el JSON
    exec 200>"$REPORT_JSON.lock"
    flock 200

    # Actualizar el JSON de forma segura
    jq --argjson new_result "$json_result" '.resultados += [$new_result]' "$REPORT_JSON" > "$REPORT_JSON.tmp" && mv "$REPORT_JSON.tmp" "$REPORT_JSON"

    # Liberar el bloqueo
    flock -u 200
    exec 200>&-
}

# Arrays de opciones de compilación

# Niveles de optimización:
OPT_LEVELS=(
    "-C opt-level=0"            # Sin optimización
    "-C opt-level=1"            # Optimización básica
    "-C opt-level=2"            # Optimización estándar
    "-C opt-level=3"            # Optimización máxima
    "-C opt-level=s"            # Optimización para tamaño
    "-C opt-level=z"            # Optimización extrema para tamaño
)

# Opciones de seguridad y optimización (una de cada categoría):
FEATURE_OPTIONS=(
    ""                          # Sin protecciones
    "-C overflow-checks=on"     # Habilita comprobaciones de desbordamiento
    "-C debug-assertions=on"    # Habilita aserciones de depuración
    "-C panic=abort"            # Aborta en caso de pánico
    "-C lto"                    # Link-Time Optimization
    "-C lto=thin"               # Thin LTO
    "-Z sanitizer=address"      # AddressSanitizer
    "-Z sanitizer=leak"         # LeakSanitizer
    "-Z sanitizer=memory"       # MemorySanitizer
    "-C link-arg=-Wl,-z,relro,-z,now"  # Full RELRO
    "-Z stack-protector=strong"  # Strong Stack canaries
    "-Z stack-protector=basic"   # Stack canaries
    "-Z stack-protector=none"    # No Stack canaries
    "-C link-arg=-Wl,-z,noexecstack"  # Pila no ejecutable
    "-C link-arg=-Wl,-z,execstack"    # Pila ejecutable
    "-C relocation-model=pic -C link-arg=-pie"       # PIE habilitado
    "-C relocation-model=static -C link-arg=-no-pie" # PIE deshabilitado
)

# Función para medir el tiempo con `date`
measure_time() {
    local start=$(date +%s.%N)
    "$@"
    local end=$(date +%s.%N)
    echo "$end - $start" | bc -l
}

# Función para obtener el uso de CPU
get_cpu_usage() {
    local pid=$1
    local cpu_usage=$(ps -o pcpu= -p "$pid" 2>/dev/null)
    [[ -z "$cpu_usage" ]] && cpu_usage="0.0"
    echo "$cpu_usage"
}

# Función para medir el consumo de memoria máxima
get_memory_usage() {
    /usr/bin/time -v "$1" 2>&1 | awk '/Maximum resident set size/ {print $6}'
}

process_combination() {
    local opt=$1
    local feature=$2

    # Archivo temporal para salida
    local temp_report=$(mktemp) || return 1

    # Determinar compilador
    local COMPILER="rustup run nightly rustc"

    # Generar nombre del ejecutable
    local EXECUTABLE="${EXECUTABLES_DIR}/program_${opt}_${feature//[^[:alnum:]]/_}"
    EXECUTABLE=$(echo "$EXECUTABLE" | tr -d ' ')

    # Encabezado en el reporte temporal
    {
        echo "==========================================="
        echo -e "${BLUE}Compilando con: $opt $feature"
    } >> "$temp_report"

    # Compilar (usamos nightly para todas las compilaciones)
    local compile_cmd="$COMPILER \"$SOURCE\" $opt $feature -o \"$EXECUTABLE\""

    if ! eval "$compile_cmd" 2>> "$temp_report"; then
        echo "Error en la compilación" >> "$temp_report"
        flock "$REPORT_FILE" cat "$temp_report" >> "$REPORT_FILE"
        rm "$temp_report"
        return 1
    fi

    # Obtener el tamaño del ejecutable
    local FILE_SIZE=$(stat -c%s "$EXECUTABLE")

    # Ejecutar el programa en segundo plano y obtener su PID
    "$EXECUTABLE" &
    local pid=$!

    # Medir tiempo de ejecución con date
    local TIME_OUTPUT=$(measure_time wait "$pid")

    # Obtener el uso de CPU
    local CPU_USAGE=$(get_cpu_usage "$pid")

    # Obtener el uso de memoria
    local MEMORY_USAGE=$(get_memory_usage "$EXECUTABLE")

    # Obtener resultados de seguridad con checksec
    local CHECKSEC_OUTPUT=$(checksec --file="$EXECUTABLE" 2>&1)

    # Filtrar la salida para JSON
    local CHECKSEC_OUTPUT_JSON=$(echo "$CHECKSEC_OUTPUT" | sed -r 's/\x1B\[[0-9;]*[mK]//g' | sed 's/\t/  /g' | tail -n 1)

    # Extraer los campos de checksec
    local RELRO=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $1}')
    local CANARY=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $2}')
    local NX=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $3}')
    local PIE=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $4}')
    local RPATH=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $5}')
    local RUNPATH=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $6}')
    local SYMBOLS=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $7}')
    local FORTIFY=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $8}')
    local FORTIFIED=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $9}')
    local FORTIFIABLE=$(echo "$CHECKSEC_OUTPUT_JSON" | awk -F '  +' '{print $10}')

    # Crear subJSON para checksec
    local CHECKSEC_JSON=$(jq -n \
        --arg relro "$RELRO" \
        --arg canary "$CANARY" \
        --arg nx "$NX" \
        --arg pie "$PIE" \
        --arg rpath "$RPATH" \
        --arg runpath "$RUNPATH" \
        --arg symbols "$SYMBOLS" \
        --arg fortify "$FORTIFY" \
        --arg fortified "$FORTIFIED" \
        --arg fortifiable "$FORTIFIABLE" \
        '{
            "RELRO": $relro,
            "CANARY": $canary,
            "NX": $nx,
            "PIE": $pie,
            "RPATH": $rpath,
            "RUNPATH": $runpath,
            "SYMBOLS": $symbols,
            "FORTIFY": $fortify,
            "Fortified": $fortified,
            "Fortifiable": $fortifiable
        }')

    # Escribir resultados en el reporte temporal
    {
        echo -e "${NC}Resultado del tiempo:"
        echo "Tiempo real: ${TIME_OUTPUT} s"
        echo "Uso de CPU: ${CPU_USAGE}%"
        echo "Memoria máxima utilizada: ${MEMORY_USAGE} KB"
        echo "Tamaño del ejecutable: ${FILE_SIZE} bytes"
        echo "-------------------------------------------"
        echo "Resultado de checksec:"
        echo "$CHECKSEC_OUTPUT"
        echo "==========================================="
        echo ""
    } >> "$temp_report"

    # Añadir al reporte principal con lock
    flock "$REPORT_FILE" cat "$temp_report" >> "$REPORT_FILE"
    rm "$temp_report"

    # Guardar en formato JSON
    local json_result=$(jq -n \
        --arg opt "$opt" \
        --arg feature "$feature" \
        --arg time "$TIME_OUTPUT" \
        --arg cpu "$CPU_USAGE" \
        --arg memory "$MEMORY_USAGE" \
        --arg size "$FILE_SIZE" \
        --argjson checksec "$CHECKSEC_JSON" \
        '{
            "optimización": $opt,
            "opción_seguridad": $feature,
            "tiempo": $time,
            "cpu_usage": $cpu,
            "memory_usage": $memory,
            "file_size": $size,
            "checksec": $checksec
        }')
    
    add_to_json "$json_result"
}

# Número máximo de trabajos paralelos
MAX_JOBS=$(nproc)
current_jobs=0

# Recorrer todas las combinaciones (nivel de optimización + una opción)
for opt in "${OPT_LEVELS[@]}"; do
    for feature in "${FEATURE_OPTIONS[@]}"; do
        # Control de trabajos concurrentes
        if (( current_jobs >= MAX_JOBS )); then
            wait -n
            ((current_jobs--))
        fi

        # Ejecutar en segundo plano
        (
            process_combination "$opt" "$feature"
        ) &
        ((current_jobs++))
    done
done

# Esperar a que terminen todos los trabajos restantes
wait

echo "Informe final guardado en $REPORT_FILE y $REPORT_JSON"
