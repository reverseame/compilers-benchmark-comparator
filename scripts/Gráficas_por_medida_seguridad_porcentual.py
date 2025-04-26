import json
import matplotlib.pyplot as plt
import numpy as np
import os
from matplotlib import rc
import matplotlib

# Configuración tipográfica profesional
rc('font',**{'family':'serif','serif':['Times'], 'size':14})
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

# Mapeo de equivalencias entre medidas de seguridad con variantes mutuamente excluyentes
SECURITY_CATEGORIES = {
    'stack-protection': {
        'variants': {
            'basic': {
                'default': {
                    'clang++': ['-fstack-protector'],
                    'g++': ['-fstack-protector'],
                    'rustc': ['-Z stack-protector=basic']
                }
            },
            'strong': {
                'default': {
                    'clang++': ['-fstack-protector-strong'],
                    'g++': ['-fstack-protector-strong'],
                    'rustc': ['-Z stack-protector=strong']
                }
            },
            'all': {
                'default': {
                    'clang++': ['-fstack-protector-all'],
                    'g++': ['-fstack-protector-all'],
                    'rustc': []
                }
            },
            'disabled': {
                'default': {
                    'clang++': ['-fno-stack-protector'],
                    'g++': ['-fno-stack-protector'],
                    'rustc': ['-Z stack-protector=none']
                }
            }
        }
    },
    'pie': {
        'variants': {
            'enabled': {
                'default': {
                    'clang++': ['-pie -fPIE'],
                    'g++': ['-pie'],
                    'rustc': ['-C relocation-model=pic -C link-arg=-pie']
                }
            },
            'disabled': {
                'default': {
                    'clang++': ['-no-pie'],
                    'g++': ['-no-pie'],
                    'rustc': ['-C relocation-model=static -C link-arg=-no-pie']
                }
            }
        }
    },
    'execstack': {
        'variants': {
            'disabled': {
                'default': {
                    'clang++': ['-z noexecstack'],
                    'g++': ['-z noexecstack'],
                    'rustc': ['-C link-arg=-Wl,-z,noexecstack']
                }
            },
            'enabled': {
                'default': {
                    'clang++': ['-Wl,-z,execstack'],
                    'g++': ['-z execstack'],
                    'rustc': ['-C link-arg=-Wl,-z,execstack']
                }
            }
        }
    },
    'sanitizers': {
        'variants': {
            'address': {
                'default': {
                    'clang++': ['-fsanitize=address'],
                    'g++': ['-fsanitize=address'],
                    'rustc': ['-Z sanitizer=address']
                }
            },
            'undefined': {
                'default': {
                    'clang++': ['-fsanitize=undefined'],
                    'g++': ['-fsanitize=undefined'],
                    'rustc': []
                }
            }
        }
    },
    'fortify-source': {
        'variants': {
            'level-2': {
                'default': {
                    'clang++': ['-D_FORTIFY_SOURCE=2'],
                    'g++': ['-D_FORTIFY_SOURCE=2'],
                    'rustc': []
                }
            },
            'level-1': {
                'default': {
                    'clang++': ['-D_FORTIFY_SOURCE=1'],
                    'g++': ['-D_FORTIFY_SOURCE=1'],
                    'rustc': []
                }
            },
            'disabled': {
                'default': {
                    'clang++': ['-D_FORTIFY_SOURCE=0'],
                    'g++': ['-U_FORTIFY_SOURCE'],
                    'rustc': []
                }
            }
        }
    },
    'relro': {
        'variants': {
            'full': {
                'default': {
                    'clang++': ['-Wl,-z,relro,-z,now'],
                    'g++': ['-Wl,-z,relro,-z,now'],
                    'rustc': ['-C link-arg=-Wl,-z,relro,-z,now']
                }
            }
        }
    },
    'safe-stack': {
        'variants': {
            'enabled': {
                'default': {
                    'clang++': ['-fsanitize=safe-stack'],
                    'g++': [],
                    'rustc': []
                }
            }
        }
    },
    'overflow-checks': {
        'variants': {
            'enabled': {
                'default': {
                    'clang++': [],
                    'g++': [],
                    'rustc': ['-C overflow-checks=on']
                }
            }
        }
    },
    'debug-assertions': {
        'variants': {
            'enabled': {
                'default': {
                    'clang++': [],
                    'g++': [],
                    'rustc': ['-C debug-assertions=on']
                }
            }
        }
    },
    'panic': {
        'variants': {
            'abort': {
                'default': {
                    'clang++': [],
                    'g++': [],
                    'rustc': ['-C panic=abort']
                }
            }
        }
    }
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

def filter_by_security_variant(data, variant_opts):
    """Filtra los datos por una variante específica de una medida de seguridad"""
    filtered_data = {}
    
    for compiler in COMPILERS:
        filtered_data[compiler] = {'resultados': []}
        expected_opts = variant_opts.get(compiler, [])
        
        for config in data[compiler].get('resultados', []):
            security_opt = config.get('opción_seguridad', '').strip()
            
            # Si no hay opciones equivalentes para este compilador, saltar
            if not expected_opts:
                continue
                
            # Verificar si la opción de seguridad coincide con alguna de las equivalentes
            for opt in expected_opts:
                if opt in security_opt:
                    filtered_data[compiler]['resultados'].append(config)
                    break
    
    return filtered_data

def get_optimization_level(config):
    """Obtiene el nivel de optimización de una configuración"""
    opt = config.get('optimización', '').strip()
    for opt_name, opt_map in OPTIMIZATIONS.items():
        for compiler, compiler_opt in opt_map.items():
            if compiler_opt and compiler_opt == opt:
                return opt_name
    return 'unknown'

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
                    not config.get('opción_seguridad', '').strip()):
                    
                    default_values[compiler][optimization] = {
                        'time': float(config.get('tiempo', 0)) * 1000,
                        'memory_usage': int(config.get('memory_usage', 0)),
                        'file_size': int(config.get('file_size', 0)) / 1024,
                        'fortified': int(config.get('checksec', {}).get('Fortified', 0)),
                        'fortifiable': int(config.get('checksec', {}).get('Fortifiable', 0))
                    }
                    break
    
    return default_values

def create_security_percentage_chart(data, metric, category_name, variant_name, subvariant_name, default_values, output_dir):
    """Crea un gráfico de porcentaje respecto a los valores por defecto para una medida de seguridad"""
    # Aumentar el tamaño de la figura
    fig, ax = plt.subplots(figsize=(14, 12))
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    
    # Variables para controlar si usamos valores absolutos
    use_absolute_values = False
    ylabel_suffix = "% Cambio respecto a default\n(positivo = peor, negativo = mejor)"
    
    # Organizar datos por compilador y optimización
    compiler_data = {}
    all_values = []  # Para almacenar todos los valores y determinar el rango del eje Y
    
    for compiler in COMPILERS:
        compiler_data[compiler] = {}
        
        for config in data[compiler].get('resultados', []):
            try:
                opt_level = get_optimization_level(config)
                if opt_level not in compiler_data[compiler]:
                    compiler_data[compiler][opt_level] = []
                
                # Obtener valor por defecto para esta métrica y optimización
                if opt_level not in default_values[compiler]:
                    continue
                    
                default_value = 0
                if metric == 'Time (ms)':
                    default_value = default_values[compiler][opt_level]['time']
                    value = float(config.get('tiempo', 0)) * 1000
                elif metric == 'Memory usage (KB)':
                    default_value = default_values[compiler][opt_level]['memory_usage']
                    value = int(config.get('memory_usage', 0))
                elif metric == 'File size (KB)':
                    default_value = default_values[compiler][opt_level]['file_size']
                    value = int(config.get('file_size', 0)) / 1024
                elif metric == 'Fortified Functions (%)':
                    fortified = int(config.get('checksec', {}).get('Fortified', 0))
                    fortifiable = int(config.get('checksec', {}).get('Fortifiable', 0))
                    value = (fortified / fortifiable * 100) if fortifiable > 0 else 0
                    
                    default_fortified = default_values[compiler][opt_level]['fortified']
                    default_fortifiable = default_values[compiler][opt_level]['fortifiable']
                    default_value = (default_fortified / default_fortifiable * 100) if default_fortifiable > 0 else 0
                else:
                    continue
                
                if metric == 'Fortified Functions (%)':
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
                
                compiler_data[compiler][opt_level].append(percentage)
            except (ValueError, TypeError, ZeroDivisionError):
                continue
    
    # Si no hay datos válidos, salir (excepto para Fortified)
    if not all_values and metric != 'Fortified Functions (%)':
        plt.close()
        return
    
    # Determinar límites del eje Y
    if metric == 'Fortified Functions (%)' and use_absolute_values:
        y_min, y_max = 0, 100
    else:
        max_abs_value = max(abs(min(all_values)), abs(max(all_values))) if all_values else 100
        y_min = -max_abs_value * 1.1  # 10% más de margen
        y_max = max_abs_value * 1.1   # 10% más de margen
    
    # Preparar datos para el gráfico
    x_positions = []
    values = []
    colors = []
    labels = []
    
    bar_width = 0.7
    group_spacing = 1.5
    
    current_pos = 0
    
    # Organizar por optimización primero, luego por compilador
    for opt_idx, optimization in enumerate(OPTIMIZATIONS.keys()):
        for comp_idx, compiler in enumerate(COMPILERS):
            # Verificar si hay datos para esta combinación
            if (optimization not in compiler_data[compiler] or 
                not compiler_data[compiler][optimization]):
                x_positions.append(current_pos)
                values.append(0)
                colors.append('black')
                labels.append('N/A')
            else:
                # Calcular promedio de los valores porcentuales
                avg_value = np.mean(compiler_data[compiler][optimization])
                x_positions.append(current_pos)
                values.append(avg_value)
                colors.append(COLORS[comp_idx])
                labels.append(f'{compiler}\n{optimization}')
            
            current_pos += 1
        
        # Añadir espacio entre grupos de optimización
        current_pos += group_spacing
    
    if not values:
        plt.close()
        return
    
    # Crear barras
    bars = ax.bar(x_positions, values, width=bar_width, color=colors, alpha=0.8,
                 edgecolor='black', linewidth=0.7)
    
    # Añadir etiquetas N/A
    for bar, label in zip(bars, labels):
        height = bar.get_height()
        if height <= 0 and label == 'N/A':
            ax.text(bar.get_x() + bar.get_width()/2., y_min * 0.05,
                    'N/A', ha='center', va='bottom', fontsize=12, 
                    rotation=90, color='black', fontweight='bold')
    
    # Configurar ejes y leyenda
    ax.set_ylabel(ylabel_suffix, fontweight='bold', labelpad=10)
    
    # Crear leyenda personalizada con tamaño reducido
    legend_elements = [
        plt.Rectangle((0,0), 1, 1, color=COLORS[0], label='clang++'),
        plt.Rectangle((0,0), 1, 1, color=COLORS[1], label='g++'),
        plt.Rectangle((0,0), 1, 1, color=COLORS[2], label='rustc')
    ]
    ax.legend(handles=legend_elements, loc='upper left', 
              bbox_to_anchor=(1.02, 1), framealpha=0.9, fontsize=12)
    
    # Configurar ticks del eje X con rotación
    xtick_positions = []
    xtick_labels = []
    
    pos = (len(COMPILERS) - 1) / 2.0
    
    for optimization in OPTIMIZATIONS.keys():
        xtick_positions.append(pos)
        xtick_labels.append(optimization)
        pos += len(COMPILERS) + group_spacing
    
    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(xtick_labels, rotation=45, ha='right')
    
    # Solo mantener la línea central en 0%
    ax.axhline(0, color='black', linewidth=0.8, linestyle='--')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0f}%'))
    
    # Añadir nota explicativa si usamos valores absolutos
    if use_absolute_values:
        ax.text(0.5, -0.15, "Nota: Se muestran valores absolutos porque el valor default es 0%", 
                ha='center', va='center', transform=ax.transAxes, fontsize=10, 
                bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))
    
    # Ajustar diseño de manera diferente para categorías problemáticas
    if category_name in ['safe-stack', 'overflow-checks', 'debug-assertions', 'panic']:
        plt.subplots_adjust(bottom=0.2, top=0.9, left=0.1, right=0.85)
    else:
        plt.tight_layout(pad=2.5, h_pad=1.5, w_pad=1.5)
    
    # Crear directorio para la medida de seguridad
    measure_dir = os.path.join(output_dir, category_name)
    
    # Solo crear subdirectorios si hay más de una variante o si no es 'default'
    category_variants = SECURITY_CATEGORIES[category_name]['variants']
    if len(category_variants) > 1 or subvariant_name != 'default':
        measure_dir = os.path.join(measure_dir, variant_name)
        if subvariant_name != 'default':
            measure_dir = os.path.join(measure_dir, subvariant_name)
    
    os.makedirs(measure_dir, exist_ok=True)
    
    # Guardar gráfico en PDF
    filename = f"{metric.replace(' ', '_').replace('(', '').replace(')', '')}_porcentaje.pdf"
    plt.savefig(os.path.join(measure_dir, filename), format="pdf", bbox_inches='tight')
    plt.close()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, '../Gráficas_por_medida_seguridad_porcentual')
    os.makedirs(output_dir, exist_ok=True)
    
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
        print("└── scripts/Gráficas_por_medida_seguridad_porcentual.py")
        return
    
    print("📊 Procesando datos...")
    data = load_data(base_dir)
    
    # Obtener valores por defecto
    print("🔍 Extrayendo valores por defecto...")
    default_values = get_default_values(data)
    
    # Generar gráficas para cada categoría de seguridad
    for category_name, category_data in SECURITY_CATEGORIES.items():
        print(f"\n🔍 Procesando categoría de seguridad: {category_name}")
        
        for variant_name, variant_data in category_data['variants'].items():
            for subvariant_name, subvariant_opts in variant_data.items():
                print(f"  ⚙️ Procesando variante: {variant_name}/{subvariant_name}")
                filtered_data = filter_by_security_variant(data, subvariant_opts)
                
                # Verificar si hay datos para al menos un compilador
                has_data = any(len(filtered_data[compiler]['resultados']) > 0 for compiler in COMPILERS)
                if not has_data:
                    print(f"  ⚠️ No hay datos para {category_name}/{variant_name}/{subvariant_name}")
                    continue
                
                print(f"  🖍️ Generando gráficas porcentuales...")
                create_security_percentage_chart(filtered_data, 'Time (ms)', category_name, variant_name, subvariant_name, default_values, output_dir)
                create_security_percentage_chart(filtered_data, 'Memory usage (KB)', category_name, variant_name, subvariant_name, default_values, output_dir)
                create_security_percentage_chart(filtered_data, 'File size (KB)', category_name, variant_name, subvariant_name, default_values, output_dir)
                create_security_percentage_chart(filtered_data, 'Fortified Functions (%)', category_name, variant_name, subvariant_name, default_values, output_dir)
    
    print(f"\n✅ Gráficos porcentuales generados exitosamente en: {output_dir}")

if __name__ == "__main__":
    main()
