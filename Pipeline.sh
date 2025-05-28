#!/bin/bash

# Verificar que se haya pasado un argumento
if [ -z "$1" ]; then
    echo "Uso: $0 <nombre_del_programa>"
    exit 1
fi

# Nombre del programa pasado como argumento
program_name=$1

# Rutas a los archivos
cpp_file="programs/${program_name}.cpp"
rs_file="programs/${program_name}.rs"

# Verificar si existen los archivos .cpp y .rs
if [ ! -f "$cpp_file" ]; then
    echo "Error: No se encontró el archivo $cpp_file"
    exit 1
fi

if [ ! -f "$rs_file" ]; then
    echo "Error: No se encontró el archivo $rs_file"
    exit 1
fi

# Ejecutar los scripts de compilación
echo "Compilando $cpp_file con g++..."
./scripts/g++.sh "$cpp_file"

echo -e "\nCompilando $cpp_file con clang++..."
./scripts/clang++.sh "$cpp_file"

echo -e "\nCompilando $rs_file con rustc..."
./scripts/rustc.sh "$rs_file"

# Ejecutar el script para obtener informes
echo -e "\nGenerando informes..."
./scripts/Obtener_informes.sh

# Ejecutar los scripts de generación de gráficas
echo -e "\nGenerando gráficas comparativas numéricas..."
echo -e "\n- Generando gráficos de rendimiento..."
python3 ./scripts/Gráficas_numéricas.py

echo -e "\nGenerando gráficas comparativas porcentuales..."
echo -e "\n- Generando gráficos de rendimiento..."
python3 ./scripts/Gráficas_porcentuales.py

echo -e "\nGenerando gráficas comparativas numéricas para cada medida de seguridad..."
echo -e "\n- Generando gráficos de rendimiento..."

python3 scripts/Gráficas_por_medida_seguridad.py

echo -e "\nGenerando gráficas comparativas numéricas para cada medida de seguridad..."
echo -e "\n- Generando gráficos de rendimiento..."

python3 scripts/Gráficas_por_medida_seguridad_porcentual.py

echo -e "\n- Generando gráfico de protecciones comparativo..."
python3 ./scripts/Gráfico_protecciones.py

echo -e "\n- Generando gráfico radar comparativo..."
python3 ./scripts/Radar_chart.py

echo -e "\n- Generando gráfico facet grid comparativo..."
python3 ./scripts/Facet_grid.py

echo -e "\n- Generando gráfico boxplot comparativo..."
python3 ./scripts/Boxplot.py

./scripts/Obtener_gráficas.sh

echo "Proceso completado."
