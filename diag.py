import pandas as pd
import matplotlib.pyplot as plt
import os


def get_unique_regions(excel_file):
    """
    Извлекает уникальные названия регионов из названий листов Excel-файла.
    """

    try:
        # Получаем все названия листов из файла
        sheets = pd.ExcelFile(excel_file).sheet_names

        # Извлекаем часть названия до последнего '_'
        regions = set()
        for sheet in sheets:
            # Разделяем по '_' и берем все части кроме последней
            parts = sheet.split('_')
            if len(parts) > 1:
                region = '_'.join(parts[:-1])  # Объединяем все части кроме последней
                regions.add(region)
            else:
                # Если нет '_', добавляем весь лист как есть
                regions.add(sheet)

        return regions

    except Exception as e:
        print(f"Ошибка при обработке файла {excel_file}: {str(e)}")
        return set()

# regions = get_unique_regions('Итоговый_файл.xlsx')


def analyze_region_data(region, excel_file, output_folder=None):
    """
    Анализирует и визуализирует данные по региону из итогового Excel-файла.
    Сохраняет графики в указанную папку.
    """

    try:
        # Загрузка данных
        df1 = pd.read_excel(excel_file, sheet_name=f'{region}_1', header=None)
        df2 = pd.read_excel(excel_file, sheet_name=f'{region}_2', header=None)

        # Извлекаем данные
        years = df1.iloc[0, 1:6].astype(int).tolist()
        total_texts = df1.iloc[1, 1:6].astype(int).tolist()
        pos1 = df1.iloc[5, 1:6].tolist()
        pos2 = df2.iloc[5, 1:6].tolist()

        # 1. Выводим данные в консоль
        print(f"\nАнализ текстов для региона: {region}")
        print("\nОбщее количество текстов по годам:")
        print(f"{'Год':<6} {'Кол-во текстов':<15}")
        for year, count in zip(years, total_texts):
            print(f"{year:<6} {count:<15}")

        print("\nПроцент позитивных текстов:")
        print(f"{'Год':<6} {'Словарь 1':<10} {'Словарь 2':<10}")
        for year, p1, p2 in zip(years, pos1, pos2):
            print(f"{year:<6} {p1:<10.2f} {p2:<10.2f}")

        # Создаем график
        plt.figure(figsize=(12, 5))

        # 2. График общего количества текстов
        plt.subplot(1, 2, 1)
        bars = plt.bar(years, total_texts, color='skyblue')
        plt.title(f'Общее количество текстов\n{region}', pad=15)
        plt.xlabel('Год')
        plt.ylabel('Количество текстов')
        plt.xticks(years)
        plt.grid(axis='y', linestyle='--', alpha=0.7)

        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width() / 2., height,
                     f'{int(height)}',
                     ha='center', va='bottom')

        # 3. График процента позитивных текстов
        plt.subplot(1, 2, 2)
        plt.plot(years, pos1, marker='o', label='Словарь 1', linewidth=2)
        plt.plot(years, pos2, marker='s', label='Словарь 2', linewidth=2)
        plt.title(f'Процент позитивных текстов\n{region}', pad=15)
        plt.xlabel('Год')
        plt.ylabel('Процент позитивных')
        plt.xticks(years)
        plt.ylim(0, 100)
        plt.legend()
        plt.grid(True)

        plt.tight_layout()

        # Сохранение или отображение графика
        if output_folder:
            # Создаем папку, если ее нет
            os.makedirs(output_folder, exist_ok=True)
            # Формируем имя файла без запрещенных символов
            filename = f"{region.replace(' ', '_').replace('/', '-')}_analysis.png"
            save_path = os.path.join(output_folder, filename)
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"\nГрафик сохранен: {save_path}")
            plt.close()
        else:
            plt.show()

    except Exception as e:
        print(f"Ошибка при обработке региона {region}: {str(e)}")


# analyze_region_data("Нижегородская область", "путь/к/другому/файлу.xlsx")