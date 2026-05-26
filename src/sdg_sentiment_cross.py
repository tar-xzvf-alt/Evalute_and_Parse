# coding: utf-8
import pandas as pd
import os
import sys
import glob
import time
from datetime import datetime
import pymorphy3
import nltk
from nltk.corpus import stopwords
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

SDG_CATEGORIES = {
    'Социальные':  [1, 2, 3, 4, 5, 6, 7, 11, 16],
    'Экономические': [8, 9, 10, 12, 17],
    'Экологические': [13, 14, 15],
}
CATEGORY_NAMES = list(SDG_CATEGORIES.keys())

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath('.'), relative_path)

morph = pymorphy3.MorphAnalyzer()
russian_stopwords = set(stopwords.words('russian'))

def load_all_dicts():
    t0 = time.time()
    dicts = {}
    for dict_id, (csv_rel, sep) in {
        1: ('data/kartaslovsent.csv', ';'),
        2: ('data/rusentilex.csv', ',')
    }.items():
        csv_path = resource_path(csv_rel)
        df = pd.read_csv(csv_path, usecols=['term', 'value'], sep=sep)
        dicts[dict_id] = dict(zip(df['term'], df['value']))
    print(f'  Словари загружены за {time.time()-t0:.1f}с', flush=True)
    return dicts

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

def lemmatize_words(texts_series):
    word_cache = {}
    def lemmatize_single(text):
        if not isinstance(text, str) or not text.strip():
            return []
        result = []
        for word in text.split():
            wl = word.lower()
            if wl not in word_cache:
                try:
                    word_cache[wl] = morph.parse(wl)[0].normal_form
                except:
                    word_cache[wl] = wl
            nf = word_cache[wl]
            if nf not in russian_stopwords:
                result.append(nf)
        return result
    return texts_series.apply(lemmatize_single)

def compute_sentiment(lemmas_list, sentiment_dict):
    scores = []
    for word in lemmas_list:
        if word in sentiment_dict:
            scores.append(sentiment_dict[word])
    if not scores:
        return None
    avg = sum(scores) / len(scores)
    return 1.0 if avg >= 0.2 else 0.0

def plot_sentiment_by_category(all_results, output_dir, timestamp):
    df = pd.DataFrame(all_results)
    regions = df['region'].unique()
    dict_names = df['dictionary'].unique()

    for dict_name in dict_names:
        ddf = df[df['dictionary'] == dict_name]
        for region in regions:
            rdf = ddf[ddf['region'] == region].sort_values(['year', 'category'])
            piv = rdf.pivot_table(values='positive_pct', index='year', columns='category', aggfunc='mean')
            if piv.empty:
                continue

            fig, ax = plt.subplots(figsize=(10, 6))
            colors = {'Социальные': '#2196F3', 'Экономические': '#FF9800', 'Экологические': '#4CAF50'}
            markers = {'Социальные': 'o', 'Экономические': 's', 'Экологические': '^'}
            for cat in CATEGORY_NAMES:
                if cat in piv.columns:
                    ax.plot(piv.index, piv[cat], marker=markers.get(cat, 'x'),
                            color=colors.get(cat, '#999'), linewidth=2, label=cat)

            ax.set_xlabel('Год')
            ax.set_ylabel('% позитивных текстов')
            ax.set_title(f'{region} — тональность по категориям ЦУР ({dict_name})')
            ax.legend(loc='best')
            ax.set_ylim(0, 100)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            safe_r = region.replace(' ', '_').replace('/', '_')
            chart_path = os.path.join(output_dir, f'{safe_r}_sentiment_{dict_name}_{timestamp}.png')
            plt.savefig(chart_path, dpi=150)
            plt.close()
            print(f'  График: {os.path.basename(chart_path)}', flush=True)

def plot_regional_comparison(all_results, output_dir, timestamp):
    df = pd.DataFrame(all_results)
    dict_names = df['dictionary'].unique()

    for dict_name in dict_names:
        ddf = df[df['dictionary'] == dict_name]
        ddf = ddf[ddf['category'] == 'Экономические']
        piv = ddf.pivot_table(values='positive_pct', index='year', columns='region', aggfunc='mean')
        if piv.empty:
            continue

        fig, ax = plt.subplots(figsize=(10, 6))
        for region in piv.columns:
            ax.plot(piv.index, piv[region], marker='o', linewidth=2, label=region)
        ax.set_xlabel('Год')
        ax.set_ylabel('% позитивных текстов (экономическая повестка)')
        ax.set_title(f'Сравнение регионов — тональность экономических ЦУР ({dict_name})')
        ax.legend(loc='best')
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        chart_path = os.path.join(output_dir, f'сравнение_регионов_эконом_{dict_name}_{timestamp}.png')
        plt.savefig(chart_path, dpi=150)
        plt.close()
        print(f'  График: {os.path.basename(chart_path)}', flush=True)

def main():
    input_dir = 'data/results_filtered'
    output_dir = 'data/sdg_sentiment_analysis'
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    xlsx_files = sorted(glob.glob(os.path.join(input_dir, '*.xlsx')))
    if not xlsx_files:
        print(f'Excel файлы не найдены в {input_dir}')
        return

    print(f'Найдено {len(xlsx_files)} файлов', flush=True)
    print('Загрузка словарей...', flush=True)
    all_dicts = load_all_dicts()

    all_results = []
    for i, fp in enumerate(xlsx_files, 1):
        fname = os.path.basename(fp)
        region, year = extract_region_year(fp)
        t0 = time.time()
        print(f'[{i}/{len(xlsx_files)}] {fname}...', end=' ', flush=True)

        df = pd.read_excel(fp)
        if 'text' not in df.columns or 'predicted_class' not in df.columns:
            print('пропущен (нет колонок)', flush=True)
            continue

        df['category'] = df['predicted_class'].apply(sdg_to_category)
        df = df[df['category'] != 'Неклассифицировано']

        lemmatized = lemmatize_words(df['text'])

        for dict_id, dict_name in [(1, 'kartaslovsent'), (2, 'rusentilex')]:
            sentiment_dict = all_dicts[dict_id]
            df['_sentiment'] = lemmatized.apply(
                lambda lemmas: compute_sentiment(lemmas, sentiment_dict))

            for cat in CATEGORY_NAMES:
                cat_sent = df[df['category'] == cat]['_sentiment']
                if len(cat_sent) == 0:
                    continue
                valid = cat_sent.dropna()
                pos_pct = (valid == 1.0).sum() / len(valid) * 100 if len(valid) > 0 else 0
                all_results.append({
                    'region': region,
                    'year': year,
                    'dictionary': dict_name,
                    'category': cat,
                    'total_texts': len(cat_sent),
                    'with_sentiment': len(valid),
                    'positive_pct': round(pos_pct, 1),
                    'negative_pct': round(100 - pos_pct, 1) if len(valid) > 0 else 0,
                })

        print(f'OK ({time.time()-t0:.1f}с)', flush=True)

    if not all_results:
        print('Нет данных для анализа')
        return

    df_out = pd.DataFrame(all_results)
    output_xlsx = os.path.join(output_dir, f'sdg_sentiment_by_category_{timestamp}.xlsx')
    df_out.to_excel(output_xlsx, index=False)
    print(f'\nТаблица сохранена: {output_xlsx}', flush=True)

    print('\nСводка по категориям (kartaslovsent):', flush=True)
    summary = df_out[df_out['dictionary'] == 'kartaslovsent'].groupby('category').agg(
        mean_positive=('positive_pct', 'mean'),
        total_texts=('total_texts', 'sum')
    ).round(1)
    print(summary, flush=True)

    print('\nГрафики...', flush=True)
    plot_sentiment_by_category(all_results, output_dir, timestamp)
    plot_regional_comparison(all_results, output_dir, timestamp)
    print('\nГотово.', flush=True)

if __name__ == '__main__':
    main()
