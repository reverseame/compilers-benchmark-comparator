#!/bin/bash

# Verificar si se proporcionó un archivo fuente como argumento
if [ "$#" -lt 1 ]; then
    echo "Uso: $0 <archivo_fuente.cpp> [<numero_de_ejecuciones>]"
    exit 1
fi

SOURCE="$1"
NUM_EJECUCIONES=${2:-1}  # Valor por defecto: 1

if [ ! -f "$SOURCE" ]; then
    echo "Error: El archivo fuente '$SOURCE' no existe."
    exit 1
fi

# Colores
BLUE='\033[0;34m'  # Azul
NC='\033[0m'       # Sin color (restablecer)

# Directorio para guardar ejecutables e informe
OUTPUT_DIR="./results_g++"
mkdir -p "$OUTPUT_DIR"
EXECUTABLES_DIR="${OUTPUT_DIR}/executables"
mkdir -p "$EXECUTABLES_DIR"

REPORT_FILE="${OUTPUT_DIR}/Informe.txt"
REPORT_JSON="${OUTPUT_DIR}/Informe.json"
{
  echo "Informe de rendimiento y seguridad"
  echo "==========================================="
  echo "Número de ejecuciones por prueba: $NUM_EJECUCIONES"
} > "$REPORT_FILE"

# Inicializamos el JSON
echo '{"resultados": [], "num_ejecuciones": '$NUM_EJECUCIONES'}' > "$REPORT_JSON"

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
OPT_LEVELS=("-O0" "-O1" "-O2" "-O3" "-Os")

# Opciones de seguridad (una de cada categoría)
SECURITY_OPTIONS=(
    ""                           # Sin protecciones
    "-no-pie"                    # Ejecutable dependiente de posición
    "-pie"                       # Ejecutable independiente de posición
    "-D_FORTIFY_SOURCE=2"        # Fortificación avanzada
    "-D_FORTIFY_SOURCE=1"        # Fortificación básica
    "-U_FORTIFY_SOURCE"          # Elimina definición de FORTIFY_SOURCE
    "-z noexecstack"             # Pila no ejecutable
    "-z execstack"               # Pila ejecutable
    "-fno-plt"                   # Desactiva PLT
    "-fsanitize=address"         # AddressSanitizer
    "-fsanitize=undefined"       # Undefined Behavior Sanitizer
    "-Wl,-z,relro,-z,now"        # Full RELRO
    "-fno-stack-protector"       # Desactiva canarios de pila
    "-fstack-protector"          # Protección básica
    "-fstack-protector-strong"   # Protección fuerte
    "-fstack-protector-all"      # Protección total
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

# Función para calcular la media de un array de números
calculate_average() {
    local round_mode="$1"
    shift
    local numbers=("$@")
    local sum=0
    local count=${#numbers[@]}

    for num in "${numbers[@]}"; do
        sum=$(echo "$sum + $num" | bc -l)
    done

    local average=$(echo "scale=9; $sum / $count" | bc -l)

    if [[ "$round_mode" == "round" ]]; then
        # Redondear al entero más cercano
        echo "$average" | awk '{printf("%d\n", ($1-int($1)>=0.5)?int($1)+1:int($1))}'
    else
        # Devolver con decimales
        echo "$average"
    fi
}

process_combination() {
    local opt=$1
    local security_opt=$2

    # Arrays para almacenar múltiples ejecuciones
    local times=()
    local cpu_usages=()
    local memory_usages=()

    # Archivo temporal para salida
    local temp_report=$(mktemp) || return 1

    # Determinar compilador
    local COMPILER="g++"

    # Generar nombre del ejecutable
    local EXECUTABLE="${EXECUTABLES_DIR}/program_${opt}_${security_opt//[^[:alnum:]]/_}"
    EXECUTABLE=$(echo "$EXECUTABLE" | tr -d ' ')

    # Encabezado en el reporte temporal
    {
        echo "==========================================="
        echo -e "${BLUE}Compilando con: $opt $security_opt"
        echo -e "Número de ejecuciones: $NUM_EJECUCIONES${NC}"
    } >> "$temp_report"

    # Compilar (solo una vez)
    local compile_cmd="$COMPILER \"$SOURCE\" $opt $security_opt -o \"$EXECUTABLE\""
    if ! eval "$compile_cmd" 2>> "$temp_report"; then
        echo "Error en la compilación" >> "$temp_report"
        flock "$REPORT_FILE" cat "$temp_report" >> "$REPORT_FILE"
        rm "$temp_report"
        return 1
    fi

    # Obtener el tamaño del ejecutable (solo una vez)
    local FILE_SIZE=$(stat -c%s "$EXECUTABLE")

    # Ejecutar el programa múltiples veces
    for ((i=1; i<=NUM_EJECUCIONES; i++)); do
        {
            echo -e "\nEjecución $i de $NUM_EJECUCIONES:"
            
            # Ejecutar el programa en segundo plano y obtener su PID
            "$EXECUTABLE" &
            local pid=$!

            # Medir tiempo de ejecución con date
            local TIME_OUTPUT=$(measure_time wait "$pid")

            # Obtener el uso de CPU
            local CPU_USAGE=$(get_cpu_usage "$pid")

            # Obtener el uso de memoria
            local MEMORY_USAGE=$(get_memory_usage "$EXECUTABLE")

            # Almacenar resultados para calcular la media después
            times+=("$TIME_OUTPUT")
            cpu_usages+=("$CPU_USAGE")
            memory_usages+=("$MEMORY_USAGE")

            echo "Tiempo: ${TIME_OUTPUT} s | CPU: ${CPU_USAGE}% | Memoria: ${MEMORY_USAGE} KB"
        } >> "$temp_report"
    done

    # Calcular medias
    local AVG_TIME=$(calculate_average "" "${times[@]}")
    local AVG_CPU=$(calculate_average "round" "${cpu_usages[@]}")
    local AVG_MEMORY=$(calculate_average "round" "${memory_usages[@]}")

    # Obtener resultados de seguridad (solo una vez)
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
        echo -e "\n${BLUE}Resultados promediados:${NC}"
        echo "Tiempo real promedio: ${AVG_TIME} s"
        echo "Uso de CPU promedio: ${AVG_CPU}%"
        echo "Memoria máxima promedio utilizada: ${AVG_MEMORY} KB"
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
        --arg security_opt "$security_opt" \
        --arg time "$AVG_TIME" \
        --arg cpu "$AVG_CPU" \
        --arg memory "$AVG_MEMORY" \
        --arg size "$FILE_SIZE" \
        --argjson checksec "$CHECKSEC_JSON" \
        '{
            "optimización": $opt,
            "opción_seguridad": $security_opt,
            "tiempo": $time,
            "cpu_usage": $cpu,
            "memory_usage": $memory,
            "file_size": $size,
            "checksec": $checksec,
            "ejecuciones": '$NUM_EJECUCIONES'
        }')
    
    add_to_json "$json_result"
}

# Número máximo de trabajos paralelos
MAX_JOBS=$(nproc)
current_jobs=0

# Recorrer todas las combinaciones (nivel de optimización + una opción de seguridad)
for opt in "${OPT_LEVELS[@]}"; do
    for security_opt in "${SECURITY_OPTIONS[@]}"; do
        # Control de trabajos concurrentes
        if (( current_jobs >= MAX_JOBS )); then
            wait -n
            ((current_jobs--))
        fi

        # Ejecutar en segundo plano
        (
            process_combination "$opt" "$security_opt"
        ) &
        ((current_jobs++))
    done
done

# Esperar a que terminen todos los trabajos restantes
wait

echo "Informe final guardado en $REPORT_FILE y $REPORT_JSON"
