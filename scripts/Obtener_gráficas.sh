#!/bin/bash

# Ruta a la carpeta Informes
INFORMES_DIR="Informes"
GRAFICAS_DIR="Gráficas_cualitativas"
GRAFICAS_NUMERICAS_DIR="Gráficas_por_optimización"
GRAFICAS_PORCENTUALES_DIR="Gráficas_por_optimización_porcentual"
GRAFICAS_SEGURIDAD_PORCENTUAL_DIR="../Gráficas_por_medida_seguridad_porcentual"

# Entrar en la carpeta Informes
cd "$INFORMES_DIR" || exit 1

# Crear las carpetas si no existen
mkdir -p "$GRAFICAS_NUMERICAS_DIR"
mkdir -p "$GRAFICAS_PORCENTUALES_DIR"
mkdir -p "$GRAFICAS_DIR"

# Array con los diferentes niveles de optimización
optimizaciones=("-O0" "-O1" "-O2" "-O3" "-Ofast" "-Os" "-Oz")

# Procesar cada nivel de optimización para gráficas numéricas
for opt in "${optimizaciones[@]}"; do
    # Crear subcarpeta para esta optimización
    carpeta_opt="${GRAFICAS_NUMERICAS_DIR}/${opt}"
    mkdir -p "$carpeta_opt"
    
    # Mover cada archivo con este prefijo y que termine en _numéricas.png
    for archivo in ./"${opt}"_*_numéricas.pdf; do
        if [ -f "$archivo" ]; then
            # Extraer la parte del nombre después del prefijo y quitar _numéricas
            nuevo_nombre="${archivo#./${opt}_}"
            nuevo_nombre="${nuevo_nombre%_numéricas.pdf}.pdf"
            # Mover el archivo renombrándolo
            mv -- "$archivo" "${carpeta_opt}/${nuevo_nombre}"
        fi
    done
done

# Procesar cada nivel de optimización para gráficas porcentuales
for opt in "${optimizaciones[@]}"; do
    # Crear subcarpeta para esta optimización
    carpeta_opt="${GRAFICAS_PORCENTUALES_DIR}/${opt}"
    mkdir -p "$carpeta_opt"
    
    # Mover cada archivo con este prefijo y que termine en _porcentuales.png
    for archivo in ./"${opt}"_*_porcentaje.pdf; do
        if [ -f "$archivo" ]; then
            # Extraer la parte del nombre después del prefijo y quitar _porcentuales
            nuevo_nombre="${archivo#./${opt}_}"
            nuevo_nombre="${nuevo_nombre%_porcentaje.pdf}.pdf"
            # Mover el archivo renombrándolo
            mv -- "$archivo" "${carpeta_opt}/${nuevo_nombre}"
        fi
    done
done

# Crear el pdf de los valores default
pdflatex valores_por_defecto.tex

# Mover el tex de valores por defecto a la carpeta Gráficas_porcentuales
if [ -f "valores_por_defecto.tex" ]; then
    mv -- "valores_por_defecto.tex" $GRAFICAS_PORCENTUALES_DIR
fi

# Mover el pdf de valores por defecto a la carpeta Gráficas_porcentuales
if [ -f "valores_por_defecto.pdf" ]; then
    mv -- "valores_por_defecto.pdf" $GRAFICAS_PORCENTUALES_DIR
fi

# Mover el gráfico de protecciones a la carpeta Gráficas_cualitativas
if [ -f "Gráfico_protecciones.pdf" ]; then
    mv -- "Gráfico_protecciones.pdf" $GRAFICAS_DIR
fi

# Mover el gráfico radar chart a la carpeta Gráficas_cualitativas
if [ -f "Comparacion_compiladores.pdf" ]; then
    mv -- "Comparacion_compiladores.pdf" $GRAFICAS_DIR
fi

# Limpiar logs de LaTeX
rm -rf valores_por_defecto*

# Mover las carpetas un nivel arriba
if [ -d "$GRAFICAS_DIR" ]; then
    mv -- "$GRAFICAS_DIR" ..
fi

if [ -d "$GRAFICAS_NUMERICAS_DIR" ]; then
    mv -- "$GRAFICAS_NUMERICAS_DIR" ..
fi

if [ -d "$GRAFICAS_PORCENTUALES_DIR" ]; then
    mv -- "$GRAFICAS_PORCENTUALES_DIR" ..
fi

# Compilar el archivo LaTeX en Gráficas_por_medida_seguridad_porcentual
if [ -f "$GRAFICAS_SEGURIDAD_PORCENTUAL_DIR/valores_por_defecto.tex" ]; then
    cd "$GRAFICAS_SEGURIDAD_PORCENTUAL_DIR" || exit 1
    pdflatex -interaction=nonstopmode valores_por_defecto.tex 

    # Limpiar archivos auxiliares de LaTeX
    rm -f valores_por_defecto.{aux,log,out}

    cd -
fi

cd ..
mkdir -p "Gráficas"
mv Gráficas_* "Gráficas"

# Mover el gráfico facet grid a la carpeta Gráficas
if [ -f "Informes/Facet_Grid.pdf" ]; then
    mv -- "Informes/Facet_Grid.pdf" "Gráficas"
fi

# Mover el gráfico boxplot a la carpeta Gráficas
if [ -f "Informes/Boxplot.pdf" ]; then
    mv -- "Informes/Boxplot.pdf" "Gráficas"
fi
echo "Las gráficas se han organizado en:"
echo "Gráficas"
echo "├── Gráficas_cualitativas"
echo "├── Gráficas_por_optimización"
echo "├── Gráficas_por_optimización_porcentual"
echo "├── Gráficas_por_medida_seguridad"
echo "└── Gráficas_por_medida_seguridad_porcentual"
