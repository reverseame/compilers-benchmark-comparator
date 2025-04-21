import json
import matplotlib.pyplot as plt
import numpy as np
import os
from matplotlib.ticker import MaxNLocator
from matplotlib import rc
import matplotlib

# Configuración tipográfica profesional
rc('font',**{'family':'serif','serif':['Times'], 'size':16})
matplotlib.rcParams['text.usetex'] = True

# Configuración estética
try:
    plt.style.use('seaborn-v0_8')
except:
    plt.style.use('ggplot')

COLORS = ['#4C72B0', '#DD8452', '#55A868']  # Azul, Naranja, Verde
COMPILERS = ['clang++', 'g++', 'rustc']

def load_data(base_path):
    """Carga los datos de todos los compiladores"""
    data = {}
    for compiler in COMPILERS:
        path = os.path.join(base_path, '../Informes', compiler, 'Informe.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content.count('{') > 1:
                    content = content[:content.rfind('}')+1]
                data[compiler] = json.loads(content)
        except Exception as e:
            print(f"⚠️ Error cargando {compiler}: {str(e)}")
            data[compiler] = {'resultados': []}
    return data

def process_features(data):
    """Procesa características de seguridad"""
    features = {
        'RELRO': {'clang++': 0, 'g++': 0, 'rustc': 0},
        'CANARY': {'clang++': 0, 'g++': 0, 'rustc': 0},
        'NX': {'clang++': 0, 'g++': 0, 'rustc': 0},
        'PIE': {'clang++': 0, 'g++': 0, 'rustc': 0},
        'FORTIFY': {'clang++': 0, 'g++': 0, 'rustc': 0}
    }
    
    for compiler in COMPILERS:
        for config in data[compiler].get('resultados', []):
            checksec = config.get('checksec', {})
            features['RELRO'][compiler] = max(features['RELRO'][compiler], 2 if 'Full' in checksec.get('RELRO', '') else 1 if 'Partial' in checksec.get('RELRO', '') else 0)
            features['CANARY'][compiler] = max(features['CANARY'][compiler], 2 if 'No canary found' not in checksec.get('CANARY', '') else 0)
            features['NX'][compiler] = max(features['NX'][compiler], 2 if 'NX enabled' in checksec.get('NX', '') else 0)
            features['PIE'][compiler] = max(features['PIE'][compiler], 2 if 'PIE enabled' in checksec.get('PIE', '') else 0)
            features['FORTIFY'][compiler] = max(features['FORTIFY'][compiler], 2 if checksec.get('FORTIFY', '') == 'Yes' else 1 if checksec.get('FORTIFY', '') == 'No' else 0)
    
    return features

def create_protection_barchart(features, output_dir):
    """Crea gráfico de barras para protecciones"""
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    bar_width = 0.25
    index = np.arange(len(features))
    
    for i, compiler in enumerate(COMPILERS):
        values = [features[cat][compiler] for cat in features]
        ax.bar(index + i*bar_width, values, bar_width,
               label=compiler, color=COLORS[i], alpha=0.8,
               edgecolor='black', linewidth=0.7)
    
    ax.set_xlabel('Protecciones', fontweight='bold')
    ax.set_ylabel('Nivel (0-2)', fontweight='bold')
    ax.set_title('Comparación de Protecciones\nEscala: 0 = N/A, 1 = Partial/No, 2 = Full/Si', 
                pad=15, fontweight='bold')
    ax.set_xticks(index + bar_width)
    ax.set_xticklabels(features.keys(), rotation=45, ha='right')
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), 
              framealpha=0.9, ncol=1, borderaxespad=0.)
    ax.set_axisbelow(True)
    ax.set_ylim(0, 2)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    plt.subplots_adjust(right=0.8)
    plt.tight_layout(rect=[0, 0, 0.85, 1])
    
    plt.savefig(os.path.join(output_dir, 'Gráfico_protecciones.pdf'), 
                format="pdf", bbox_inches='tight')
    plt.close()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, '../Informes')
    
    required_dirs = [
        os.path.join(base_dir, '../Informes', 'clang++'),
        os.path.join(base_dir, '../Informes', 'g++'),
        os.path.join(base_dir, '../Informes', 'rustc')
    ]
    
    if not all(os.path.exists(d) for d in required_dirs):
        print("❌ Error: Estructura de directorios incorrecta")
        print("La estructura requerida es:")
        print("├── Informes/")
        print("│   ├── clang++/Informe.json")
        print("│   ├── g++/Informe.json")
        print("│   └── rustc/Informe.json")
        print("└── scripts/Gráfico_protecciones.py")
        return
    
    print("📊 Procesando datos para gráfico de protecciones...")
    data = load_data(base_dir)
    print("\n🔍 Analizando características de seguridad...")
    features = process_features(data)
    print("\n🖍️ Generando gráfico de protecciones...")
    create_protection_barchart(features, output_dir)
    print(f"\n✅ Gráfico de protecciones generado exitosamente en: {output_dir}")

if __name__ == "__main__":
    main()
