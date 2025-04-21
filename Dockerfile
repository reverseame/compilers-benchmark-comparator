FROM debian:bookworm-slim

# 1. Configurar variables de entorno
ENV PATH="/root/.cargo/bin:${PATH}"
ENV RUSTUP_HOME="/root/.rustup"
ENV CARGO_HOME="/root/.cargo"
ENV DEBIAN_FRONTEND=noninteractive

# 2. Instalar todas las dependencias en una sola capa
RUN apt-get update && apt-get install -y \
    # Compiladores y herramientas básicas
    build-essential \
    clang \
    llvm \
    curl \
    python3 \
    python3-pip \
    jq \
    bc \
    time \
    checksec \
    git \
    # Dependencias para gráficos y PDFs
    aha \
    wkhtmltopdf \
    pandoc \
    texlive-full \
    lmodern \
    fonts-freefont-otf \
    # Herramientas de seguridad
    binutils-dev \
    libcap-dev \
    libseccomp-dev \
    # Dependencias de runtime
    libpython3.11 \
    && rm -rf /var/lib/apt/lists/*

# 3. Instalar Rust y herramientas
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain nightly && \
    rustup component add rust-src rustfmt clippy && \
    cargo install --locked cargo-binutils

# 4. Instalar bibliotecas Python
RUN pip3 install --break-system-packages --no-cache-dir matplotlib pandas seaborn numpy scipy statsmodels

# 5. Configurar fuentes para matplotlib
RUN mkdir -p /usr/share/fonts/truetype/freefont && \
    ln -s /usr/share/fonts/truetype/freefont/FreeSans.ttf /usr/share/fonts/truetype/ && \
    fc-cache -fv

# 6. Copiar el proyecto y configurar permisos
COPY . /app
WORKDIR /app
RUN chmod +x Pipeline.sh scripts/*.sh scripts/*.py

# 7. Configurar punto de entrada
ENTRYPOINT ["./Pipeline.sh"]
