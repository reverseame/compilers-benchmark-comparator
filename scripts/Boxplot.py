import json
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import seaborn as sns
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

# Mapeo completo de optimizaciones por compilador
OPTIMIZATIONS = {
    '-O0': {'clang++': '-O0', 'g++': '-O0', 'rustc': '-C opt-level=0'},
    '-O1': {'clang++': '-O1', 'g++': '-O1', 'rustc': '-C opt-level=1'},
    '-O2': {'clang++': '-O2', 'g++': '-O2', 'rustc': '-C opt-level=2'},
    '-O3': {'clang++': '-O3', 'g++': '-O3', 'rustc': '-C opt-level=3'},
    '-Os': {'clang++': '-Os', 'g++': '-Os', 'rustc': '-C opt-level=s'},
    '-Oz': {'clang++': '-Oz', 'g++': None, 'rustc': '-C opt-level=z'},
    '-Ofast': {'clang++': '-Ofast', 'g++': None, 'rustc': None}
}

def load_data(base_path):
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

def filter_by_optimization(data, optimization):
    filtered_data = {}
    opt_info = OPTIMIZATIONS[optimization]
    
    for compiler in COMPILERS:
        filtered_data[compiler] = {'resultados': []}
        expected_opt = opt_info[compiler]
        
        if expected_opt is None:
            continue
            
        for config in data[compiler].get('resultados', []):
            if config.get('optimización', '').strip() == expected_opt:
                filtered_data[compiler]['resultados'].append(config)
    
    return filtered_data

def get_security_options(config):
    seguridad = config.get('opción_seguridad', '')
    return seguridad if seguridad else 'default'

def create_boxplot_grid(data, output_dir):
    metrics_data = []
    
    for optimization in OPTIMIZATIONS.keys():
        filtered_data = filter_by_optimization(data, optimization)
        
        for compiler in COMPILERS:
            expected_opt = OPTIMIZATIONS[optimization][compiler]
            
            if expected_opt is None:
                continue
                
            for config in filtered_data[compiler].get('resultados', []):
                security = get_security_options(config)
                
                try:
                    time_val = float(config.get('tiempo', 0)) * 1000
                    if time_val > 0:
                        metrics_data.append({
                            'Compiler': compiler,
                            'Metric': 'Time (ms)',
                            'Value': time_val,
                            'Security': security
                        })
                except (ValueError, TypeError):
                    pass
                
                try:
                    mem_usage = int(config.get('memory_usage', 0))
                    if mem_usage > 0:
                        metrics_data.append({
                            'Compiler': compiler,
                            'Metric': 'Memory usage (KB)',
                            'Value': mem_usage,
                            'Security': security
                        })
                except (ValueError, TypeError):
                    pass
                
                try:
                    mem_size = int(config.get('file_size', 0)) / 1024
                    if mem_size > 0:
                        metrics_data.append({
                            'Compiler': compiler,
                            'Metric': 'File size (KB)',
                            'Value': mem_size,
                            'Security': security
                        })
                except (ValueError, TypeError):
                    pass
                
                try:
                    fortified = int(config.get('checksec', {}).get('Fortified', 0))
                    fortifiable = int(config.get('checksec', {}).get('Fortifiable', 0))
                    if fortifiable > 0:
                        percentage = (fortified / fortifiable) * 100
                        metrics_data.append({
                            'Compiler': compiler,
                            'Metric': r'Fortified Functions (\%)',
                            'Value': percentage,
                            'Security': security
                        })
                except (ValueError, TypeError):
                    pass
    
    df = pd.DataFrame(metrics_data)
    df = df.dropna(subset=['Value'])
    
    metric_order = [
        'Time (ms)', 
        'Memory usage (KB)', 
        'File size (KB)', 
        r'Fortified Functions (\%)'
    ]
    df['Metric'] = pd.Categorical(df['Metric'], categories=metric_order, ordered=True)
    
    plt.rcParams['axes.titlesize'] = 14
    plt.rcParams['axes.titlepad'] = 12
    plt.rcParams['axes.labelpad'] = 10
    plt.rcParams['xtick.major.pad'] = 5
    plt.rcParams['text.usetex'] = True
    plt.rcParams['text.latex.preamble'] = r'\usepackage{amsmath}'
    
    fig, axes = plt.subplots(2, 2, figsize=(20, 16))
    axes = axes.flatten()
    
    palette = {compiler: color for compiler, color in zip(COMPILERS, COLORS)}
    
    for i, metric in enumerate(metric_order):
        ax = axes[i]
        subset = df[df['Metric'] == metric]
        
        sns.boxplot(data=subset, x='Compiler', y='Value', hue='Compiler', palette=palette, ax=ax)

        if ax.get_legend():
            ax.get_legend().remove()
        
        ax.set_title(metric, pad=20, fontsize=14, fontweight='bold')
        ax.set_ylabel('')
        ax.set_xlabel('')
        
        for j, compiler in enumerate(COMPILERS):
            ax.text(j, ax.get_ylim()[0] * 0.95, compiler, 
                    ha='center', va='top', fontsize=11,
                    color='black', fontweight='bold')
        
        ax.set_xticklabels([])
        y_min, y_max = ax.get_ylim()
        ax.set_ylim(y_min * 0.98, y_max * 1.02)
        ax.grid(True, axis='y', linestyle='--', alpha=0.3)
    
    plt.tight_layout()
    
    filename = os.path.join(output_dir, "Boxplot.pdf")
    plt.savefig(filename, format="pdf", bbox_inches='tight', dpi=300)
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
        print("└── scripts/Boxplot.py")
        return
    
    print("📊 Procesando datos para Boxplot Grid...")
    data = load_data(base_dir)
    print("\n📦 Generando Boxplots...")
    create_boxplot_grid(data, output_dir)
    print(f"\n✅ Boxplot generado exitosamente en: {output_dir}")

if __name__ == "__main__":
    main()

