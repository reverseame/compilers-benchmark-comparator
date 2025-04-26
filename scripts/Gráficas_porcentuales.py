import json
import matplotlib.pyplot as plt
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

def get_default_values(data):
    """Obtiene los valores por defecto (sin flags de seguridad) para cada compilador y optimización"""
    default_values = {}
    
    for compiler in COMPILERS:
        default_values[compiler] = {}
        for optimization in OPTIMIZATIONS:
            opt_flag = OPTIMIZATIONS[optimization][compiler]
            if opt_flag is None:
                continue
                
            # Buscar configuración sin flags de seguridad
            for config in data[compiler].get('resultados', []):
                if (config.get('optimización', '').strip() == opt_flag and 
                    get_security_options(config) == 'default'):
                    
                    default_values[compiler][optimization] = {
                        'time': float(config.get('tiempo', 0)) * 1000,
                        'memory_usage': int(config.get('memory_usage', 0)),
                        'file_size': int(config.get('file_size', 0)) / 1024,
                        'fortified': int(config.get('checksec', {}).get('Fortified', 0)),
                        'fortifiable': int(config.get('checksec', {}).get('Fortifiable', 0))
                    }
                    break
    
    return default_values

def generate_latex_table(default_values, output_dir):
    """Genera una tabla LaTeX con los valores por defecto usando booktabs"""
    latex_table = """\\documentclass{article}
\\usepackage[utf8]{inputenc}
\\usepackage{booktabs}
\\usepackage{tabularx}
\\usepackage{geometry}
\\usepackage{array}
\\geometry{a4paper, margin=1in}

\\begin{document}

\\begin{table}[ht]
\\centering
\\caption{Valores por defecto (sin flags de seguridad)}
\\small
\\begin{tabularx}{\\textwidth}{l l >{\\centering\\arraybackslash}X >{\\centering\\arraybackslash}X >{\\centering\\arraybackslash}X >{\\centering\\arraybackslash}X}
\\toprule
Compilador & Optimización & \\multicolumn{1}{c}{Time (ms)} & \\multicolumn{1}{c}{Memory usage (KB)} & \\multicolumn{1}{c}{File size (KB)} & \\multicolumn{1}{c}{Fortified functions (\\%)} \\\\
\\midrule
"""
    
    for compiler in COMPILERS:
        first_row = True
        for optimization in OPTIMIZATIONS:
            if optimization not in default_values[compiler]:
                continue
                
            values = default_values[compiler][optimization]
            fortified_pct = (values['fortified'] / values['fortifiable'] * 100) if values['fortifiable'] > 0 else 0.0
            
            if first_row:
                latex_table += f"{compiler} & {optimization} & {values['time']:.2f} & {values['memory_usage']} & {values['file_size']:.2f} & {fortified_pct:.1f} \\\\\n"
                first_row = False
            else:
                latex_table += f" & {optimization} & {values['time']:.2f} & {values['memory_usage']} & {values['file_size']:.2f} & {fortified_pct:.1f} \\\\\n"
        
        # Añadir separador entre compiladores, excepto después del último
        if compiler != COMPILERS[-1]:
            latex_table += "\\midrule\n"
    
    latex_table += """\\bottomrule
\\end{tabularx}
\\end{table}

\\end{document}"""
    
    # Guardar tabla LaTeX
    with open(os.path.join(output_dir, 'valores_por_defecto.tex'), 'w', encoding='utf-8') as f:
        f.write(latex_table)

def get_security_options(config):
    """Extrae directamente el campo opción_seguridad del JSON"""
    seguridad = config.get('opción_seguridad', '')
    return seguridad if seguridad else 'default'

def create_percentage_chart(data, metric, optimization, default_values, output_dir):
    """Crea un gráfico de porcentaje respecto a los valores por defecto"""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    
    # Variables para controlar si usamos valores absolutos
    use_absolute_values = False
    ylabel_suffix = "% Cambio respecto a default\n(positivo = peor, negativo = mejor)"
    
    # Organizar datos por compilador
    compiler_data = {}
    all_values = []  # Para almacenar todos los valores y determinar el rango del eje Y
    
    for compiler in COMPILERS:
        compiler_data[compiler] = []
        expected_opt = OPTIMIZATIONS[optimization][compiler]
        
        # Si la optimización no existe para este compilador, añadir N/A
        if expected_opt is None or optimization not in default_values[compiler]:
            compiler_data[compiler].append({
                'value': None,
                'security': 'N/A',
                'compiler': compiler
            })
            continue
            
        # Obtener valor por defecto para esta métrica
        default_value = 0
        if metric == 'Time (ms)':
            default_value = default_values[compiler][optimization]['time']
        elif metric == 'Memory usage (KB)':
            default_value = default_values[compiler][optimization]['memory_usage']
        elif metric == 'File size (KB)':
            default_value = default_values[compiler][optimization]['file_size']
        elif metric == 'Fortified (%)':
            fortified = default_values[compiler][optimization]['fortified']
            fortifiable = default_values[compiler][optimization]['fortifiable']
            default_value = (fortified / fortifiable * 100) if fortifiable > 0 else 0
            
        for config in data[compiler].get('resultados', []):
            try:
                security_opts = get_security_options(config)
                if security_opts == 'default':
                    continue
                    
                if metric == 'Time (ms)':
                    value = float(config.get('tiempo', 0)) * 1000
                elif metric == 'Memory usage (KB)':
                    value = int(config.get('memory_usage', 0))
                elif metric == 'File size (KB)':
                    value = int(config.get('file_size', 0)) / 1024
                elif metric == 'Fortified (%)':
                    fortified = int(config.get('checksec', {}).get('Fortified', 0))
                    fortifiable = int(config.get('checksec', {}).get('Fortifiable', 0))
                    value = (fortified / fortifiable * 100) if fortifiable > 0 else 0
                else:
                    continue
                
                if metric == 'Fortified (%)':
                    if default_value == 0:
                        # Usar valor absoluto y marcarlo
                        percentage = value
                        use_absolute_values = True
                        ylabel_suffix = "Porcentaje de funciones fortificadas (valor absoluto)"
                    else:
                        percentage = ((value - default_value) / default_value) * 100
                else:
                    if default_value <= 0:
                        continue
                    percentage = ((value - default_value) / default_value) * 100
                
                all_values.append(percentage)
                
                compiler_data[compiler].append({
                    'value': percentage,
                    'security': security_opts,
                    'compiler': compiler
                })
            except (ValueError, TypeError, ZeroDivisionError):
                continue
    
    # Si no hay datos válidos, salir (excepto para Fortified)
    if not all_values and metric != 'Fortified (%)':
        plt.close()
        return
    
    # Determinar límites del eje Y
    if metric == 'Fortified (%)' and use_absolute_values:
        y_min, y_max = 0, 100  # Rango fijo 0-100% para valores absolutos
    else:
        max_abs_value = max(abs(min(all_values)), abs(max(all_values))) if all_values else 100
        y_min = -max_abs_value * 1.1  # 10% más de margen
        y_max = max_abs_value * 1.1   # 10% más de margen
    
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
    
    ax.grid(True, axis='y', linestyle='--', alpha=0.3)

    # Crear barras
    bars = ax.bar(x_positions, values, width=bar_width, color=colors, alpha=0.8,
                 edgecolor='black', linewidth=0.7)
    
    # Añadir etiquetas de seguridad
    for bar, label in zip(bars, security_labels):
        height = bar.get_height()
        if height <= 0 and label == 'N/A':
            ax.text(bar.get_x() + bar.get_width()/2., y_min * 0.05,
                    'N/A', ha='center', va='bottom', fontsize=12, 
                    rotation=90, color='black', fontweight='bold')
        else:
            va = 'bottom' if height >= 0 else 'top'
            y_pos = height + (0.02 * y_max if height >=0 else 0.02 * y_min)
            ax.text(bar.get_x() + bar.get_width()/2., y_pos,
                    label, ha='center', va=va, fontsize=9, rotation=90)
    
    # Configurar ejes
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

    # Configurar etiquetas de ejes
    ax.set_ylabel(ylabel_suffix, fontweight='bold')
    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(COMPILERS, fontsize=11, fontweight='bold')
    ax.set_ylim(y_min, y_max)
    
    # Añadir nota explicativa si usamos valores absolutos
    if use_absolute_values:
        ax.text(0.5, -0.15, "Nota: Se muestran valores absolutos porque el valor default es 0%", 
                ha='center', va='center', transform=ax.transAxes, fontsize=10, 
                bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))
    
    # Solo mantener la línea central en 0%
    ax.axhline(0, color='black', linewidth=0.8, linestyle='--')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0f}%'))
    
    plt.tight_layout()
    
    # Guardar gráfico en PDF
    if metric == 'Fortified (%)':
        filename = f"{optimization}_Fortified_Functions_porcentaje.pdf"
    else:
        filename = f"{optimization}_{metric.replace(' ', '_').replace('(', '').replace(')', '')}_porcentaje.pdf"
    
    plt.savefig(os.path.join(output_dir, filename), format="pdf", bbox_inches='tight')
    plt.close()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, '../Informes')
    
    # Verificar estructura de directorios
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
        print("└── scripts/Graficas_porcentuales.py")
        return
    
    print("📊 Procesando datos...")
    data = load_data(base_dir)
    
    # Obtener valores por defecto
    print("🔍 Extrayendo valores por defecto...")
    default_values = get_default_values(data)
    
    # Generar tabla LaTeX
    print("📝 Generando tabla LaTeX...")
    generate_latex_table(default_values, output_dir)
    
    # Gráfico de protecciones
    print("🔍 Analizando características de seguridad...")
    print("🖍️ Generando gráfico de protecciones...")
    
    # Gráficos de rendimiento porcentuales
    for optimization in OPTIMIZATIONS.keys():
        print(f"\n🔍 Procesando optimización: {optimization}")
        filtered_data = filter_by_optimization(data, optimization)
        
        print("🖍️ Generando gráficos porcentuales...")
        create_percentage_chart(filtered_data, 'Time (ms)', optimization, default_values, output_dir)
        create_percentage_chart(filtered_data, 'Memory usage (KB)', optimization, default_values, output_dir)
        create_percentage_chart(filtered_data, 'File size (KB)', optimization, default_values, output_dir)
        create_percentage_chart(filtered_data, 'Fortified (%)', optimization, default_values, output_dir)
    
    output_dir = os.path.join(base_dir, '../Gráficas_porcentuales')
    print(f"\n✅ Gráficos generados exitosamente en: {output_dir}")

if __name__ == "__main__":
    main()
