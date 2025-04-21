#!/bin/bash

# Crear la carpeta Informes si no existe
mkdir -p Informes

# Recorrer cada directorio que comience con "results_"
for dir in results_*; do
    # Verificar si es un directorio
    if [ -d "$dir" ]; then
        # Extraer el nombre del compilador (eliminando el prefijo "results_")
        compilador="${dir#results_}"

        # Crear la carpeta correspondiente dentro de Informes
        mkdir -p "Informes/$compilador"

        # Entrar al directorio
        cd "$dir"

        # Generar el archivo HTML a partir del Informe.txt
        cat Informe.txt | aha --black --title "Informe de Compilación" > Informe.html

        # Convertir el HTML a PDF
        wkhtmltopdf Informe.html Informe.pdf

        # Eliminar el archivo HTML temporal
        rm Informe.html

        # Copiar los archivos Informe.pdf, Informe.txt e Informe.json a la carpeta correspondiente en Informes
        cp Informe.pdf "../Informes/$compilador/"
        cp Informe.txt "../Informes/$compilador/"
        cp Informe.json "../Informes/$compilador/"

        # Volver al directorio anterior
        cd ..
    fi
done

rm -rf results_*

echo "Los informes se han generado y organizado en la carpeta Informes."
