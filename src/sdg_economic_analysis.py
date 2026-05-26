# coding: utf-8
import pandas as pd
import os
import sys
import glob
from datetime import datetime
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

SDG_CATEGORIES = {
    'Социальные':  [1, 2, 3, 4, 5, 6, 7, 11, 16],
    'Экономические': [8, 9, 10, 12, 17],
    'Экологические': [13, 14, 15],
}

CATEGORY_NAMES = list(SDG_CATEGORIES.keys())

def sdg_to_category(predicted_class):
    num = int(predicted_class.replace('SDG', '').strip())
    for cat, goals in SDG_CATEGORIES.items():
        if num in goals:
            return cat
    return 'Неклассифицировано'

def extract_region_year(filename):
    base = os.path.basename(filename).replace('.xlsx', '')
    parts = base.split('_')
    region = parts[0]
    year = None
    for p in parts:
        if p.isdigit() and len(p) == 4:
            year = int(p)
            break
    return region, year

def process_file(filepath):
    df = pd.read_excel(filepath)
    if 'predicted_class' not in df.columns:
        return None
    df['category'] = df['predicted_class'].apply(sdg_to_category)
    region, year = extract_region_year(filepath)
    counts = df['category'].value_counts()
    total = len(df)
    result = {'region': region, 'year': year, 'total': total}
    for cat in CATEGORY_NAMES:
        result[f'{cat}_count'] = counts.get(cat, 0)
        result[f'{cat}_pct'] = round(counts.get(cat, 0) / total * 100, 1)
    return result

def plot_regional_distribution(stats_df, output_dir, timestamp):
    regions = stats_df['region'].unique()
    for region in regions:
        rdf = stats_df[stats_df['region'] == region].sort_values('year')
        years = rdf['year'].tolist()
        x = np.arange(len(years))
        width = 0.6

        fig, ax = plt.subplots(figsize=(10, 6))
        bottom = np.zeros(len(years))
        colors = {'Социальные': '#2196F3', 'Экономические': '#FF9800', 'Экологические': '#4CAF50'}
        for cat in CATEGORY_NAMES:
            vals = rdf[f'{cat}_count'].values
            ax.bar(x, vals, width, bottom=bottom, label=cat, color=colors.get(cat, '#999'))
            bottom += vals

        ax.set_xlabel('Год')
        ax.set_ylabel('Количество текстов')
        ax.set_title(f'{region} — распределение по категориям ЦУР')
        ax.set_xticks(x)
        ax.set_xticklabels(years)
        ax.legend(loc='upper right')
        plt.tight_layout()
        safe_region = region.replace(' ', '_').replace('/', '_')
        chart_path = os.path.join(output_dir, f'{safe_region}_категории_ЦУР_{timestamp}.png')
        plt.savefig(chart_path, dpi=150)
        plt.close()
        print(f'  Сохранён график: {chart_path}')

def plot_percentage_comparison(stats_df, output_dir, timestamp):
    regions = stats_df['region'].unique()
    fig, axes = plt.subplots(len(regions), 1, figsize=(12, 4 * len(regions)), sharex=True)
    if len(regions) == 1:
        axes = [axes]

    colors = {'Социальные': '#2196F3', 'Экономические': '#FF9800', 'Экологические': '#4CAF50'}
    for ax, region in zip(axes, regions):
        rdf = stats_df[stats_df['region'] == region].sort_values('year')
        width = 0.2
        x = np.arange(len(rdf))
        for i, cat in enumerate(CATEGORY_NAMES):
            vals = rdf[f'{cat}_pct'].values
            ax.bar(x + i * width, vals, width, label=cat, color=colors.get(cat, '#999'))
        ax.set_ylabel('% текстов')
        ax.set_title(f'{region}')
        ax.set_xticks(x + width)
        ax.set_xticklabels(rdf['year'].tolist())
        ax.legend(loc='upper right')
        ax.set_ylim(0, 100)

    plt.tight_layout()
    chart_path = os.path.join(output_dir, f'сравнение_категорий_ЦУР_{timestamp}.png')
    plt.savefig(chart_path, dpi=150)
    plt.close()
    print(f'  Сохранён сводный график: {chart_path}')

def main():
    input_dir = 'data/results_filtered'
    output_dir = 'data/sdg_category_analysis'
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    xlsx_files = sorted(glob.glob(os.path.join(input_dir, '*.xlsx')))
    if not xlsx_files:
        print(f'Excel файлы не найдены в {input_dir}')
        return

    print(f'Найдено {len(xlsx_files)} файлов')
    all_stats = []
    for fp in xlsx_files:
        fname = os.path.basename(fp)
        print(f'Обработка: {fname}')
        stats = process_file(fp)
        if stats:
            all_stats.append(stats)
            region, year = stats['region'], stats['year']
            social_pct = stats['Социальные_pct']
            economic_pct = stats['Экономические_pct']
            env_pct = stats['Экологические_pct']
            print(f'  {region} {year}: {stats["total"]} текстов, '
                  f'соц={social_pct}%, экон={economic_pct}%, экол={env_pct}%')

    if not all_stats:
        print('Нет данных для анализа')
        return

    stats_df = pd.DataFrame(all_stats)
    stats_df = stats_df.sort_values(['region', 'year'])
    output_xlsx = os.path.join(output_dir, f'sdg_category_distribution_{timestamp}.xlsx')
    stats_df.to_excel(output_xlsx, index=False)
    print(f'\nСохранена таблица: {output_xlsx}')

    print('\nПостроение графиков...')
    plot_regional_distribution(stats_df, output_dir, timestamp)
    plot_percentage_comparison(stats_df, output_dir, timestamp)
    print('\nГотово.')

if __name__ == '__main__':
    main()
