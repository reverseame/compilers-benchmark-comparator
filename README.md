# Compilers Benchmark Comparator

Este repositorio contiene una pipeline que se encarga de realizar gráficas comparativas de medidas de rendimiento y seguridad en compiladores modernos, en concreto de g++, clang++ y rustc. Además ha sido mi TFG presentado en la EINA, Universidad de Zaragoza.

## Contenido

- **Pipeline.sh**: Es el programa principal.
- **scripts**: Es la carpeta que contiene todos los scripts que se ejecutarán para poder realizar la ejecución completa.
- **programs**: Es la carpeta donde están los programas de prueba o donde se deberían añadir nuevos para poder comparar.
- **Dockerfile** y **docker-compose.yml**: Archivos para poder desplegar la aplicación en docker si no se desea usar un sistema debian nativo.

## Requisitos
Tener un programa con el mismo nombre que sea cpp y rs.

### Nativo

- Haber instalado las siguientes dependencias en un sistema basado en debian: build-essential, clang, llvm, curl, python3, python3-pip, jq, bc, time, checksec, git, aha, wkhtmltopdf, texlive-latex-base, texlive-latex-extra, texlive-fonts-recommended, dvipng, cm-super, ghostscript, fonts-liberation, fonts-freefont-otf, binutils-dev, libcap-dev, libseccomp-dev, python3-dev

- Tener instalado los compiladores de c++, clang++ y rustc (en su version nightly).

- Tener las siguientes librerias de python instaladas: matplotlib, pandas, seaborn, numpy, scipy, statsmodels.

- Tener configuradas las fuentes para matplotlib (mirar Dockerfile si hay dudas).

```sh
sudo apt install build-essential clang llvm curl python3 python3-pip jq bc time checksec git aha texlive-latex-base texlive-latex-extra texlive-fonts-recommended dvipng cm-super ghostscript fonts-liberation fonts-freefont-otf binutils-dev libcap-dev libseccomp-dev python3-dev
```

> **Nota para `wkhtmltopdf`**: Si usas distribuciones recientes (como Kali Linux, Debian 13 o Ubuntu 24.04), `wkhtmltopdf` ya no está en los repositorios oficiales. Puedes instalarlo descargando el paquete `.deb` manualmente:
> ```sh
> wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
> sudo apt install ./wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
> ```

```sh 
pip3 install -r requirements.txt
```

### Docker

- Tener instalado docker y docker-compose.
- Poseer al menos 3 gigas para la imagen de docker.

## Instalación y Uso

Clona el repositorio:
```sh
git clone https://github.com/DonJulve/Compilers-Benchmark-Comparator
```

**Nota**: 
 - nombre_del_programa es el nombre del programa a usar para medir sin extensión, osea si tengo suma.cpp y suma.rs pondría solo suma.
 - numero_de_ejecuciones es opcional y por defecto es 1, se usa para poder hacer una media de las ejecuciones.

### Nativo

```sh
./Pipeline <nombre_del_programa> [<numero_de_ejecuciones>]
```

### Docker
```sh
# Descargar la imagen pre-construida (opcional, docker-compose la bajará si no la tienes)
docker-compose pull

# Levantar contenedores
docker-compose up -d

# Ejecutar el benchmark
docker-compose run benchmark <nombre_del_programa> [<numero_de_ejecuciones>]
```

**Eliminar imagen**
```sh
docker-compose down
docker rmi compiler-benchmark
```

## Teclonogías empleadas:

- **Shell**: Lenguaje de scripting usado para poder ejecutar grandes cantidades de comandos para compilación, ejecución y medición.
- **Python**: Lenguaje usado para generar las gráficas y tratar los datos de las mediciones realizadas.
- **Docker**: Herramienta de contenedores utilizada para empaquetar y distribuir la aplicación.
- **C++** y **rust**: Ambos lenguajes no están directamente presentes en el proyecto pero se ha estudiado su comportamiento y sus compiladores para poder realizar el proyecto.

