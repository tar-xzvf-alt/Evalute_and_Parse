import pandas as pd
import os
from pathlib import Path

def split_excel_by_class(input_file, output_dir=None):
    """
    Разделяет Excel файл на отдельные файлы по классам
    
    Parameters:
    input_file: путь к входному Excel файлу
    output_dir: папка для сохранения результатов (если None, создается папка рядом с файлом)
    """
    
    # Чтение Excel файла
    try:
        df = pd.read_excel(input_file)
    except Exception as e:
        print(f"Ошибка при чтении файла {input_file}: {e}")
        return
    
    # Проверка наличия необходимых колонок
    if 'text' not in df.columns or 'predicted_class' not in df.columns:
        print(f"Файл {input_file} не содержит колонок 'text' и/или 'predicted_class'")
        return
    
    # Определяем выходную директорию
    if output_dir is None:
        # Создаем папку с именем исходного файла (без расширения)
        base_name = Path(input_file).stem
        output_dir = Path(input_file).parent / f"{base_name}_split"
    
    # Создаем выходную директорию
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Получаем базовое имя исходного файла
    original_filename = Path(input_file).stem
    
    # Группируем по классам и сохраняем
    for class_name, group in df.groupby('predicted_class'):
        # Создаем имя файла: исходное имя + класс
        # Очищаем имя класса от недопустимых символов для имени файла
        safe_class_name = class_name.replace('/', '_').replace('\\', '_').replace(':', '_')
        output_file = output_dir / f"{original_filename}_{safe_class_name}.xlsx"
        
        # Сохраняем только колонку text
        group[['text']].to_excel(output_file, index=False)
        print(f"Создан файл: {output_file} (текстов: {len(group)})")
    
    print(f"\nОбработка файла {input_file} завершена. Файлы сохранены в: {output_dir}")

def process_all_excel_files(input_dir, output_base_dir=None):
    """
    Обрабатывает все Excel файлы в указанной директории
    
    Parameters:
    input_dir: папка с исходными Excel файлами
    output_base_dir: базовая папка для сохранения результатов
    """
    
    input_path = Path(input_dir)
    
    # Ищем все Excel файлы
    excel_files = list(input_path.glob("*.xlsx")) + list(input_path.glob("*.xls"))
    
    if not excel_files:
        print(f"Excel файлы не найдены в {input_dir}")
        return
    
    print(f"Найдено {len(excel_files)} Excel файлов")
    
    for excel_file in excel_files:
        print(f"\n{'='*50}")
        print(f"Обработка файла: {excel_file.name}")
        print(f"{'='*50}")
        
        if output_base_dir:
            # Создаем подпапку для каждого файла
            file_output_dir = Path(output_base_dir) / excel_file.stem
        else:
            file_output_dir = None
            
        split_excel_by_class(excel_file, file_output_dir)

# Пример использования:

# Вариант 1: Обработать один файл
#input_file = "Астраханская область_посты_2024_filtered_20260219_013434.xlsx"
#split_excel_by_class(input_file)

# Вариант 2: Обработать все Excel файлы в папке
# input_directory = "путь/к/папке/с/excel/файлами"
# process_all_excel_files(input_directory)

# Вариант 3: Обработать все файлы и сохранить в отдельную папку
input_directory = "results_filtered"
output_directory = "results_filtered/results_sdg"

process_all_excel_files(input_directory, output_directory)