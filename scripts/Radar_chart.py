import json
import matplotlib.pyplot as plt
import numpy as np
import os
from matplotlib import rc
import matplotlib

# Configuración tipográfica profesional
rc('font',**{'family':'serif','serif':['Times'], 'size':16})
matplotlib.rcParams['text.usetex'] = True
# Añadir paquetes necesarios para LaTeX
matplotlib.rcParams['text.latex.preamble'] = r'\usepackage{amsmath} \usepackage{amssymb}'

def parse_checksec_data(compiler_data):
    features = {
        'RELRO': 0,
        'CANARY': 0,
        'NX': 0,
        'PIE': 0,
        'FORTIFY': 0,
    }
    
    for config in compiler_data['resultados']:
        checksec = config.get('checksec', {})
        
        # RELRO scoring
        relro = checksec.get('RELRO', '')
        if 'Full RELRO' in relro:
            features['RELRO'] = max(features['RELRO'], 2)
        elif 'Partial RELRO' in relro:
            features['RELRO'] = max(features['RELRO'], 1)
        else:
            features['RELRO'] = max(features['RELRO'], 0)

        # CANARY scoring
        canary = checksec.get('CANARY', '')
        if 'Canary found' in canary:
            features['CANARY'] = max(features['CANARY'], 2)
        elif 'No canary found' in canary:
            features['CANARY'] = max(features['CANARY'], 1)
        else:
            features['CANARY'] = max(features['CANARY'], 0)
        
        # NX scoring
        nx = checksec.get('NX', '')
        if 'NX enabled' in nx:
            features['NX'] = max(features['NX'], 2)
        elif 'NX disabled' in nx:
            features['NX'] = max(features['NX'], 1)
        else:
            features['NX'] = max(features['NX'], 0)
        
        # PIE scoring
        pie = checksec.get('PIE', '')
        if 'PIE enabled' in pie:
            features['PIE'] = max(features['PIE'], 2)
        elif 'PIE disabled' in pie:
            features['PIE'] = max(features['PIE'], 1)
        else:
            features['PIE'] = max(features['PIE'], 0)
        
        # FORTIFY scoring
        fortify = checksec.get('FORTIFY', '')
        if fortify == 'Yes':
            features['FORTIFY'] = max(features['FORTIFY'], 2)
        elif fortify == 'No':
            features['FORTIFY'] = max(features['FORTIFY'], 1)
        else:
            features['FORTIFY'] = max(features['FORTIFY'], 0)

    return features

def load_compiler_data(base_path, compiler_name):
    json_path = os.path.join(base_path, '../Informes', compiler_name, 'Informe.json')
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # Manejar JSON mal formados o con múltiples objetos
            if content.startswith('{') and content.endswith('}'):
                return json.loads(content)
            elif content.count('{') > 1:
                # Tomar solo el primer objeto JSON si hay múltiples
                first_obj = content[:content.rfind('}')+1]
                return json.loads(first_obj)
            else:
                raise ValueError("Formato JSON no reconocido")
    except Exception as e:
        print(f"Error al leer {json_path}: {str(e)}")
        return {'resultados': []}

def create_radar_chart(base_path):
    # Cargar datos para cada compilador
    clang_data = load_compiler_data(base_path, 'clang++')
    gpp_data = load_compiler_data(base_path, 'g++')
    rustc_data = load_compiler_data(base_path, 'rustc')
    
    # Verificar que tenemos datos válidos
    if not clang_data['resultados'] or not gpp_data['resultados'] or not rustc_data['resultados']:
        print("Error: Uno o más archivos JSON no contienen datos válidos")
        return
    
    # Procesar características de seguridad
    clang_features = parse_checksec_data(clang_data)
    gpp_features = parse_checksec_data(gpp_data)
    rustc_features = parse_checksec_data(rustc_data)
    
    # Configuración del gráfico
    categories = list(clang_features.keys())
    num_vars = len(categories)
    
    # Ángulos para cada eje
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    angles += angles[:1]  # Completar el círculo
    
    # Crear figura
    fig, ax = plt.subplots(figsize=(14, 14), subplot_kw=dict(polar=True))
    
    # Función para preparar datos (cerrar el círculo)
    def prepare_data(features):
        values = list(features.values())
        return values + values[:1]
    
    # Dibujar cada compilador
    ax.plot(angles, prepare_data(clang_features), 'o-', linewidth=3, 
            label='clang++', color='#1f77b4', markersize=8)
    ax.fill(angles, prepare_data(clang_features), alpha=0.25, color='#1f77b4')
    
    ax.plot(angles, prepare_data(gpp_features), 'o-', linewidth=3,
            label='g++', color='#ff7f0e', markersize=8)
    ax.fill(angles, prepare_data(gpp_features), alpha=0.25, color='#ff7f0e')
    
    ax.plot(angles, prepare_data(rustc_features), 'o-', linewidth=3,
            label='rustc', color='#2ca02c', markersize=8)
    ax.fill(angles, prepare_data(rustc_features), alpha=0.25, color='#2ca02c')
    
    # Configurar ejes
    ax.set_ylim(0, 2)
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(['0', '1', '2'], fontsize=12)
    ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.7)
    
    # Etiquetas y título
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=14, fontweight='bold')
    ax.set_title('Comparación de Compiladores\n', 
                fontsize=18, pad=30, fontweight='bold')
    
    # Leyenda de métricas
    metrics_legend = (
        r"\textbf{Leyenda de Métricas:}" + "\n" +
        r"\rule{3cm}{0.4pt}" + "\n" +
        r"$\bullet$ RELRO: 0=None \textbar\ 1=Partial \textbar\ 2=Full" + "\n" +
        r"$\bullet$ CANARY: 0=N/A \textbar\ 1=No \textbar\ 2=Sí" + "\n" +
        r"$\bullet$ NX: 0=N/A \textbar\ 1=Disabled \textbar\ 2=Enabled" + "\n" +
        r"$\bullet$ PIE: 0=N/A \textbar\ 1=No \textbar\ 2=Sí" + "\n" +
        r"$\bullet$ FORTIFY: 0=N/A \textbar\ 1=No \textbar\ 2=Sí"
    )
    
    # Añadir leyenda al gráfico
    plt.figtext(
        0.9, 0.8, metrics_legend,
        ha='center', va='top',
        bbox=dict(facecolor='#f5f5f5', edgecolor='gray', boxstyle='round', alpha=0.8),
        fontsize=11,
        usetex=True
    )
    
    # Leyenda de compiladores
    ax.legend(
        loc='upper right',
        bbox_to_anchor=(1.35, 1.15),
        shadow=True,
        fontsize=12,
        framealpha=0.9
    )
    
    # Guardar resultados en PDF
    output_pdf = os.path.join(base_path, '../Informes', 'Comparacion_compiladores.pdf')
    plt.tight_layout()
    plt.savefig(output_pdf, format="pdf", bbox_inches='tight')
    
    print("📊 Procesando datos...")
    print("🔍 Analizando características de seguridad...")
    print("🖍️ Generando gráfico...")
    print(f"\n✅ Gráfico guardado en: {output_pdf}")
    plt.close()

if __name__ == "__main__":
    project_base = os.path.dirname(os.path.abspath(__file__))
    
    # Verificar estructura de directorios
    required_dirs = [
        os.path.join(project_base, '../Informes', 'clang++'),
        os.path.join(project_base, '../Informes', 'g++'),
        os.path.join(project_base, '../Informes', 'rustc')
    ]
    
    if not all(os.path.exists(d) for d in required_dirs):
        print("Error: Estructura de directorios incorrecta")
        print("La estructura debe ser:")
        print("├── Informes/")
        print("│   ├── clang++/Informe.json")
        print("│   ├── g++/Informe.json")
        print("│   └── rustc/Informe.json")
        print("└── scripts/Radar_chart.py")
    else:
        create_radar_chart(project_base)
