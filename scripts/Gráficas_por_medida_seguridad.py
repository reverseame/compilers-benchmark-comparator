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

def create_security_measure_chart(data, metric, category_name, variant_name, subvariant_name, output_dir):
    """Crea un gráfico comparando una medida de seguridad entre optimizaciones"""
    fig, ax = plt.subplots(figsize=(14, 12))
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    
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
                
                if metric == 'Time (ms)':
                    value = float(config.get('tiempo', 0)) * 1000
                elif metric == 'Memory usage (KB)':
                    value = int(config.get('memory_usage', 0))
                elif metric == 'File size (KB)':
                    value = int(config.get('file_size', 0)) / 1024
                elif metric == 'Fortified Functions (%)':
                    fortified = int(config.get('checksec', {}).get('Fortified', 0))
                    fortifiable = int(config.get('checksec', {}).get('Fortifiable', 0))
                    value = (fortified / fortifiable) * 100 if fortifiable > 0 else 0
                else:
                    continue
                
                if value <= 0:
                    continue
                    
                compiler_data[compiler][opt_level].append(value)
                all_values.append(value)
            except (ValueError, TypeError):
                continue
    
    # Determinar límites del eje Y
    if metric == 'Fortified Functions (%)':
        y_min, y_max = 0, 100  # Porcentajes fijos entre 0 y 100
    else:
        y_min = max(min(all_values) * 0.9, 0) if all_values else 0  # 10% de margen inferior, mínimo 0
        y_max = max(all_values) * 1.1 if all_values else 100  # 10% de margen superior
    
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
            if optimization not in compiler_data[compiler] or not compiler_data[compiler][optimization]:
                x_positions.append(current_pos)
                values.append(0)
                colors.append('black')
                labels.append('N/A')
            else:
                # Calcular promedio de los valores
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
    
    # Establecer límites del eje Y
    ax.set_ylim(y_min, y_max)
    
    # Crear barras
    bars = ax.bar(x_positions, values, width=bar_width, color=colors, alpha=0.8,
                 edgecolor='black', linewidth=0.7)
    
    # Añadir etiquetas N/A
    base_level = max(y_min, 0)
    for bar, label in zip(bars, labels):
        height = bar.get_height()
        if height <= 0 and label == 'N/A':
            ax.text(bar.get_x() + bar.get_width()/2., base_level + (y_max - base_level) * 0.01,
                    'N/A', ha='center', va='bottom', fontsize=12, 
                    rotation=90, color='black', fontweight='bold')
    
    # Configurar ejes y leyenda
    ax.set_ylabel(f'{metric}', fontweight='bold')
    
    # Crear leyenda personalizada
    legend_elements = [
        plt.Rectangle((0,0), 1, 1, color=COLORS[0], label='clang++'),
        plt.Rectangle((0,0), 1, 1, color=COLORS[1], label='g++'),
        plt.Rectangle((0,0), 1, 1, color=COLORS[2], label='rustc')
    ]
    ax.legend(handles=legend_elements, loc='upper left', 
              bbox_to_anchor=(1.02, 1), framealpha=0.9)
    
    # Configurar ticks del eje X
    xtick_positions = []
    xtick_labels = []
    
    pos = (len(COMPILERS) - 1) / 2.0
    
    for optimization in OPTIMIZATIONS.keys():
        xtick_positions.append(pos)
        xtick_labels.append(optimization)
        pos += len(COMPILERS) + group_spacing
    
    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(xtick_labels, rotation=45, ha='right')
    
    # Ajustar márgenes de manera diferente para categorías problemáticas
    problematic_categories = ['safe-stack', 'overflow-checks', 'debug-assertions', 
                            'panic', 'sanitizers', 'fortify-source']
    
    if category_name in problematic_categories:
        plt.subplots_adjust(bottom=0.25, top=0.9, left=0.1, right=0.85)
    else:
        plt.tight_layout()
    
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
    filename = metric.replace(' ', '_').replace('(', '').replace(')', '').replace('%', '')
    # Eliminar cualquier _ adicional al final antes de .pdf
    filename = filename.rstrip('_') + '.pdf'
    plt.savefig(os.path.join(measure_dir, filename), format="pdf", bbox_inches='tight')
    plt.close()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, '../Gráficas_por_medida_seguridad')
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
        print("└── scripts/Gráficas_por_medida_seguridad.py")
        return
    
    print("📊 Procesando datos...")
    data = load_data(base_dir)
    
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
                
                print(f"  🖍️ Generando gráficas...")
                create_security_measure_chart(filtered_data, 'Time (ms)', category_name, variant_name, subvariant_name, output_dir)
                create_security_measure_chart(filtered_data, 'Memory usage (KB)', category_name, variant_name, subvariant_name, output_dir)
                create_security_measure_chart(filtered_data, 'File size (KB)', category_name, variant_name, subvariant_name, output_dir)
                create_security_measure_chart(filtered_data, 'Fortified Functions (%)', category_name, variant_name, subvariant_name, output_dir)
    
    print(f"\n✅ Gráficos generados exitosamente en: {output_dir}")

if __name__ == "__main__":
    main()
