import json
import matplotlib.pyplot as plt
import numpy as np
import os
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

plt.rcParams['axes.grid'] = True
plt.rcParams['grid.linestyle'] = '--'
plt.rcParams['grid.alpha'] = 0.3
plt.rcParams['grid.color'] = 'gray'


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

def filter_by_optimization(data, optimization):
    """Filtra los datos por nivel de optimización"""
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
    """Extrae directamente el campo opción_seguridad del JSON"""
    seguridad = config.get('opción_seguridad', '')
    return seguridad if seguridad else 'default'

def create_individual_chart(data, metric, optimization, output_dir):
    """Crea un gráfico individual para una métrica específica"""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    
    # Organizar datos por compilador
    compiler_data = {}
    for compiler in COMPILERS:
        compiler_data[compiler] = []
        expected_opt = OPTIMIZATIONS[optimization][compiler]
        
        if expected_opt is None:
            compiler_data[compiler].append({
                'value': None,
                'security': 'N/A',
                'compiler': compiler
            })
            continue
            
        for config in data[compiler].get('resultados', []):
            try:
                if metric == 'Time (ms)':
                    value = float(config.get('tiempo', 0)) * 1000
                elif metric == 'Memory usage (KB)':
                    value = int(config.get('memory_usage', 0))
                elif metric == 'File size (KB)':
                    value = int(config.get('file_size', 0)) / 1024
                else:
                    continue
                
                if value <= 0:
                    continue
                    
                security_opts = get_security_options(config)
                compiler_data[compiler].append({
                    'value': value,
                    'security': security_opts,
                    'compiler': compiler
                })
            except (ValueError, TypeError):
                continue
    
    # Preparar datos para el gráfico
    x_positions = []
    values = []
    colors = []
    security_labels = []
    
    bar_width = 0.7
    group_spacing = 1.5
    
    current_pos = 0
    
    for i, compiler in enumerate(COMPILERS):
        if not compiler_data[compiler]:
            x_positions.append(current_pos)
            values.append(0)
            colors.append('black')
            security_labels.append('N/A')
            current_pos += 1
            current_pos += group_spacing
            continue
            
        security_options = sorted(set(item['security'] for item in compiler_data[compiler]))
        
        for security in security_options:
            for item in compiler_data[compiler]:
                if item['security'] == security:
                    x_positions.append(current_pos)
                    values.append(item['value'] if item['value'] is not None else 0)
                    colors.append(COLORS[i] if item['value'] is not None else 'black')
                    security_labels.append(item['security'])
                    current_pos += 1
        
        current_pos += group_spacing
    
    if not values:
        plt.close()
        return
    
    # Crear grid de fondo
    ax.grid(True, axis='y', linestyle='--', alpha=0.3)
    
    # Crear barras
    bars = ax.bar(x_positions, values, width=bar_width, color=colors, alpha=0.8,
                 edgecolor='black', linewidth=0.7)
    
    for bar, label in zip(bars, security_labels):
        height = bar.get_height()
        if height <= 0 and label == 'N/A':
            ax.text(bar.get_x() + bar.get_width()/2., 0.1,
                    'N/A', ha='center', va='bottom', fontsize=12, 
                    rotation=90, color='black', fontweight='bold')
        elif height > 0:
            ax.text(bar.get_x() + bar.get_width()/2., height*1.02,
                    label, ha='center', va='bottom', fontsize=9, rotation=90)
    
    xtick_positions = []
    group_size = []
    
    for compiler in COMPILERS:
        size = len(compiler_data[compiler])
        if size == 0:
            size = 1
        group_size.append(size)
    
    pos = 0
    for size in group_size:
        if size > 0:
            center = pos + (size - 1) / 2
            xtick_positions.append(center)
        else:
            xtick_positions.append(pos)
        pos += size + group_spacing

    ax.set_ylabel(f'{metric}', fontweight='bold')
    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(COMPILERS, fontsize=11, fontweight='bold')
    
    plt.tight_layout()
    filename = f"{optimization}_{metric.replace(' ', '_').replace('(', '').replace(')', '')}_numéricas.pdf"
    plt.savefig(os.path.join(output_dir, filename), format="pdf", bbox_inches='tight')
    plt.close()

def create_fortification_chart(data, optimization, output_dir):
    """Crea gráfico de funciones fortificadas"""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')

    compiler_data = {}
    for compiler in COMPILERS:
        compiler_data[compiler] = []
        expected_opt = OPTIMIZATIONS[optimization][compiler]
        
        if expected_opt is None:
            compiler_data[compiler].append({
                'value': None,
                'security': 'N/A',
                'compiler': compiler
            })
            continue
            
        for config in data[compiler].get('resultados', []):
            try:
                fortified = int(config.get('checksec', {}).get('Fortified', 0))
                fortifiable = int(config.get('checksec', {}).get('Fortifiable', 0))
                
                if fortifiable > 0:
                    percentage = (fortified / fortifiable) * 100
                else:
                    percentage = 0
                    
                security_opts = get_security_options(config)
                compiler_data[compiler].append({
                    'value': percentage,
                    'security': security_opts,
                    'compiler': compiler
                })
            except (ValueError, TypeError):
                continue
    
    x_positions = []
    values = []
    colors = []
    security_labels = []
    
    bar_width = 0.7
    group_spacing = 1.5
    
    current_pos = 0
    
    for i, compiler in enumerate(COMPILERS):
        if not compiler_data[compiler]:
            x_positions.append(current_pos)
            values.append(0)
            colors.append('black')
            security_labels.append('N/A')
            current_pos += 1
            current_pos += group_spacing
            continue
            
        security_options = sorted(set(item['security'] for item in compiler_data[compiler]))
        
        for security in security_options:
            for item in compiler_data[compiler]:
                if item['security'] == security:
                    x_positions.append(current_pos)
                    values.append(item['value'] if item['value'] is not None else 0)
                    colors.append(COLORS[i] if item['value'] is not None else 'black')
                    security_labels.append(item['security'])
                    current_pos += 1
        
        current_pos += group_spacing
    
    if not values:
        plt.close()
        return
    
    # Crear grid de fondo
    ax.grid(True, axis='y', linestyle='--', alpha=0.3)
    
    bars = ax.bar(x_positions, values, width=bar_width, color=colors, alpha=0.8,
                 edgecolor='black', linewidth=0.7)
    
    for bar, label in zip(bars, security_labels):
        height = bar.get_height()
        if height <= 0 and label == 'N/A':
            ax.text(bar.get_x() + bar.get_width()/2., 0.1,
                    'N/A', ha='center', va='bottom', fontsize=12, 
                    rotation=90, color='black', fontweight='bold')
        elif height > 0:
            ax.text(bar.get_x() + bar.get_width()/2., height*1.02,
                    label, ha='center', va='bottom', fontsize=9, rotation=90)
    
    xtick_positions = []
    group_size = []
    
    for compiler in COMPILERS:
        size = len(compiler_data[compiler])
        if size == 0:
            size = 1
        group_size.append(size)
    
    pos = 0
    for size in group_size:
        if size > 0:
            center = pos + (size - 1) / 2
            xtick_positions.append(center)
        else:
            xtick_positions.append(pos)
        pos += size + group_spacing

    ax.set_ylabel(f'Fortified Functions (%)', fontweight='bold')
    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(COMPILERS, fontsize=11, fontweight='bold')
    
    plt.tight_layout()
    filename = f"{optimization}_Fortified_Functions_numéricas.pdf"
    plt.savefig(os.path.join(output_dir, filename), format="pdf", bbox_inches='tight')
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
        print("└── scripts/Gráficas_numéricas.py")
        return
    
    print("📊 Procesando datos para gráficos individuales...")
    data = load_data(base_dir)
    
    for optimization in OPTIMIZATIONS.keys():
        print(f"\n🔍 Procesando optimización: {optimization}")
        filtered_data = filter_by_optimization(data, optimization)
        
        print("🖍️ Generando gráficos numéricos individuales...")
        create_individual_chart(filtered_data, 'Time (ms)', optimization, output_dir)
        create_individual_chart(filtered_data, 'Memory usage (KB)', optimization, output_dir)
        create_individual_chart(filtered_data, 'File size (KB)', optimization, output_dir)
        create_fortification_chart(filtered_data, optimization, output_dir)
    
    print(f"\n✅ Todos los gráficos individuales generados exitosamente en: {output_dir}")

if __name__ == "__main__":
    main()
