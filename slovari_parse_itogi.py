# coding: utf8

import os
import pandas as pd
import diag


def get_all_info_about_folders(base_folder):

    final_file = process_regional_data(base_folder)
    unique_regions = diag.get_unique_regions(final_file)

    for region in unique_regions:
        diag.analyze_region_data(region,final_file,base_folder+"/Графики по папкам")


def process_regional_data(base_folder):
    """
    Обрабатывает данные из Excel-файлов в подпапках указанной папки и сохраняет результаты в итоговый Excel-файл."""
    data = {}

    # Обход всех папок
    for folder in os.listdir(base_folder):
        folder_path = os.path.join(base_folder, folder)
        if os.path.isdir(folder_path):  # Проверяем, что это папка
            for file in os.listdir(folder_path):
                if file.endswith("_итоги.xlsx"):  # Проверяем, что это Excel файл
                    file_path = os.path.join(folder_path, file)
                    # Извлечение тематики и года из названия файла
                    temp = file[:-11].split("_")
                    region, _, year, dict_id = temp
                    year = int(year)
                    region_and_dict = region + "_" + dict_id
                    # Чтение данных из Excel файла
                    df = pd.read_excel(file_path, skiprows=1, nrows=5, header=None)
                    values = df[1].tolist()  # Извлекаем значения из второго столбца
                    # Добавляем данные в словарь
                    if region_and_dict not in data:
                        data[region_and_dict] = {}
                    data[region_and_dict][year] = values

    # Создание Excel файла с отдельными листами для каждого региона
    output_file = base_folder+"/Итоговый_файл.xlsx"
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        for region, years in data.items():
            # Формируем таблицу для региона
            df = pd.DataFrame(
                years,
                index=["Всего текстов", "Всего негативных", "Всего позитивных",
                       "Процент негативных", "Процент позитивных"]
            ).sort_index(axis=1)  # Сортируем года по возрастанию
            # Сохраняем таблицу на отдельный лист
            df.to_excel(writer, sheet_name=region)

    print(f"Данные успешно сохранены в файл: {output_file}")
    return output_file
