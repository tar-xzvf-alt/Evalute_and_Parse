# coding: utf-8
"""Experimental robustness checks for SDG sentiment analysis.

This script does not replace the main Kendall/FE pipeline. It adds two exploratory checks:
1) panel FE regressions after min-max and z-softmax normalization;
2) SDG-specific Kendall correlations for selected goals and Rosstat indicators.
"""
import os
import re
from pathlib import Path

import nltk
import numpy as np
import pandas as pd
import pymorphy3
import statsmodels.api as sm
from nltk.corpus import stopwords
from scipy.special import softmax
from scipy.stats import kendalltau


INPUT_DIR = Path('data/results_filtered')
ROSTAT_PATH = Path('data/region_stats/region_indicators.csv')
MERGED_PATH = Path('data/correlation_analysis/merged_data.csv')
DICT_PATH = Path('data/kartaslovsent.csv')
OUTPUT_DIR = Path('data/correlation_analysis')

YEAR_MIN = 2020
YEAR_MAX = 2023
MIN_TOTAL_TEXTS = 10
MIN_OBS = 6

SELECTED_SDGS = [3, 8, 9, 11, 13, 15]

SDG_INDICATOR_PAIRS = {
    3: [
        ('doctors_per_10k', 'Врачей на 10 тыс.'),
        ('hospital_beds_per_10k', 'Коек на 10 тыс.'),
        ('deaths_per_100k', 'Смертность на 100 тыс.'),
    ],
    8: [
        ('grp_per_capita', 'ВРП на душу, руб.'),
        ('average_monthly_wage', 'Среднемесячная зарплата, руб.'),
        ('investment_per_capita', 'Инвестиции на душу, руб.'),
    ],
    9: [
        ('investment_per_capita', 'Инвестиции на душу, руб.'),
    ],
    11: [
        ('doctors_per_10k', 'Врачей на 10 тыс.'),
        ('hospital_beds_per_10k', 'Коек на 10 тыс.'),
        ('retail_trade_per_capita', 'Оборот розницы на душу, руб.'),
    ],
    13: [
        ('emissions_thousand_tons', 'Выбросы в атмосферу, тыс. т'),
        ('environmental_spending_per_capita', 'Расходы на охрану среды на душу, руб.'),
    ],
    15: [
        ('emissions_thousand_tons', 'Выбросы в атмосферу, тыс. т'),
        ('environmental_spending_per_capita', 'Расходы на охрану среды на душу, руб.'),
    ],
}

REGRESSION_PAIRS = [
    ('pos_economic', 'grp_per_capita'),
    ('pos_economic', 'investment_per_capita'),
    ('pos_social', 'unemployment_pct'),
    ('pos_social', 'grp_per_capita'),
    ('pos_environmental', 'emissions_thousand_tons'),
    ('Экологические_pct', 'grp_per_capita'),
    ('Социальные_pct', 'unemployment_pct'),
    ('Экономические_pct', 'investment_per_capita'),
]


def ensure_stopwords():
    try:
        nltk.data.find('corpora/stopwords')
    except LookupError:
        nltk.download('stopwords')


def extract_region_year(path):
    base = path.stem
    parts = base.split('_')
    region = parts[0]
    year = None
    for part in parts:
        if part.isdigit() and len(part) == 4:
            year = int(part)
            break
    return region, year


def normalize_sdg(value):
    match = re.search(r'(\d+)', str(value))
    if not match:
        return None
    return int(match.group(1))


def load_sentiment_dict():
    df = pd.read_csv(DICT_PATH, sep=';', usecols=['term', 'value'])
    return dict(zip(df['term'], df['value']))


def build_lemmatizer():
    ensure_stopwords()
    morph = pymorphy3.MorphAnalyzer()
    russian_stopwords = set(stopwords.words('russian'))
    cache = {}

    def lemmatize(text):
        if not isinstance(text, str) or not text.strip():
            return []
        words = re.findall(r'[A-Za-zА-Яа-яЁё]+', text.lower())
        result = []
        for word in words:
            if word not in cache:
                try:
                    cache[word] = morph.parse(word)[0].normal_form
                except Exception:
                    cache[word] = word
            lemma = cache[word]
            if lemma not in russian_stopwords:
                result.append(lemma)
        return result

    return lemmatize


def compute_binary_sentiment(text, lemmatize, sentiment_dict):
    scores = [sentiment_dict[word] for word in lemmatize(text) if word in sentiment_dict]
    if not scores:
        return np.nan
    avg = sum(scores) / len(scores)
    return 1.0 if avg >= 0.2 else 0.0


def panel_fe_regression(data, y_col, x_col):
    df = data[['region', 'year', y_col, x_col]].dropna().copy()
    if len(df) < 6:
        return None
    dummies = pd.get_dummies(df['region'], drop_first=True, dtype=float)
    x = pd.concat([df[[x_col]], dummies], axis=1)
    x = sm.add_constant(x, has_constant='add')
    y = df[y_col]
    try:
        model = sm.OLS(y, x).fit()
    except Exception:
        return None
    return model.params[x_col], model.pvalues[x_col], model.rsquared, len(df)


def minmax(series):
    span = series.max() - series.min()
    if pd.isna(span) or span == 0:
        return pd.Series(np.nan, index=series.index)
    return (series - series.min()) / span


def z_softmax(series):
    valid = series.dropna()
    result = pd.Series(np.nan, index=series.index, dtype=float)
    if len(valid) == 0:
        return result
    std = valid.std(ddof=0)
    if std == 0 or pd.isna(std):
        z_values = np.zeros(len(valid))
    else:
        z_values = (valid - valid.mean()) / std
    result.loc[valid.index] = softmax(z_values)
    return result


def compute_normalized_regressions():
    merged = pd.read_csv(MERGED_PATH)
    rows = []
    for method in ['raw', 'minmax', 'z_softmax']:
        data = merged.copy()
        if method != 'raw':
            cols = sorted(set([col for pair in REGRESSION_PAIRS for col in pair]))
            for col in cols:
                norm_col = f'{col}__norm'
                data[norm_col] = minmax(data[col]) if method == 'minmax' else z_softmax(data[col])

        for y_col, x_col in REGRESSION_PAIRS:
            y_use = y_col if method == 'raw' else f'{y_col}__norm'
            x_use = x_col if method == 'raw' else f'{x_col}__norm'
            res = panel_fe_regression(data, y_use, x_use)
            if res is None:
                continue
            coef, pval, r2, n = res
            rows.append({
                'normalization': method,
                'dependent': y_col,
                'independent': x_col,
                'beta': round(coef, 6),
                'p_value': round(pval, 4),
                'r2': round(r2, 4),
                'n': n,
            })
    return pd.DataFrame(rows)


def load_rostat():
    rostat = pd.read_csv(ROSTAT_PATH)
    rostat['retail_trade_per_capita'] = rostat['retail_trade'] * 1e6 / (rostat['population'] * 1e3)
    rostat['environmental_spending_per_capita'] = rostat['environmental_spending'] * 1e6 / (rostat['population'] * 1e3)
    return rostat[(rostat['year'] >= YEAR_MIN) & (rostat['year'] <= YEAR_MAX)].copy()


def compute_sdg_sentiment():
    sentiment_dict = load_sentiment_dict()
    lemmatize = build_lemmatizer()
    records = []

    files = sorted(INPUT_DIR.glob('*.xlsx'))
    for path in files:
        region, year = extract_region_year(path)
        if year is None or year < YEAR_MIN or year > YEAR_MAX:
            continue
        df = pd.read_excel(path)
        if 'text' not in df.columns or 'predicted_class' not in df.columns:
            continue
        df['sdg'] = df['predicted_class'].apply(normalize_sdg)
        df = df[df['sdg'].isin(SELECTED_SDGS)].copy()
        if df.empty:
            continue
        df['_sentiment'] = df['text'].apply(lambda text: compute_binary_sentiment(text, lemmatize, sentiment_dict))
        for sdg, group in df.groupby('sdg'):
            valid = group['_sentiment'].dropna()
            positive_pct = np.nan
            if len(valid) > 0:
                positive_pct = (valid == 1.0).sum() / len(valid) * 100
            records.append({
                'region': region,
                'year': year,
                'sdg': int(sdg),
                'total_texts': len(group),
                'with_sentiment': len(valid),
                'positive_pct': round(positive_pct, 2) if not pd.isna(positive_pct) else np.nan,
            })

    result = pd.DataFrame(records)
    return result.sort_values(['sdg', 'region', 'year']).reset_index(drop=True)


def compute_sdg_kendall(sdg_sentiment, rostat):
    rows = []
    for sdg, pairs in SDG_INDICATOR_PAIRS.items():
        sdg_df = sdg_sentiment[sdg_sentiment['sdg'] == sdg]
        merged = sdg_df.merge(rostat, on=['region', 'year'], how='inner')
        for indicator, indicator_name in pairs:
            all_subset = merged[['positive_pct', 'total_texts', indicator]].dropna()
            filtered = all_subset[all_subset['total_texts'] >= MIN_TOTAL_TEXTS]
            for sample_name, subset in [('all_available', all_subset), ('min_10_texts', filtered)]:
                if len(subset) >= MIN_OBS:
                    tau, pval = kendalltau(subset['positive_pct'], subset[indicator])
                else:
                    tau, pval = np.nan, np.nan
                rows.append({
                    'sdg': sdg,
                    'sample': sample_name,
                    'indicator': indicator_name,
                    'indicator_column': indicator,
                    'kendall_tau': round(tau, 3) if not pd.isna(tau) else np.nan,
                    'p_value': round(pval, 4) if not pd.isna(pval) else np.nan,
                    'n': len(subset),
                    'min_total_texts': int(subset['total_texts'].min()) if len(subset) else 0,
                    'median_total_texts': round(subset['total_texts'].median(), 1) if len(subset) else 0,
                })
    return pd.DataFrame(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    norm_reg = compute_normalized_regressions()
    norm_reg_path = OUTPUT_DIR / 'experimental_normalized_panel_regressions.csv'
    norm_reg.to_csv(norm_reg_path, index=False, float_format='%.6f')
    print(f'Нормированные FE-регрессии: {norm_reg_path}')
    print(norm_reg.to_string(index=False))

    rostat = load_rostat()
    sdg_sentiment = compute_sdg_sentiment()
    sdg_sent_path = OUTPUT_DIR / 'experimental_sdg_specific_sentiment.csv'
    sdg_sentiment.to_csv(sdg_sent_path, index=False, float_format='%.2f')
    print(f'\nSDG-specific sentiment: {sdg_sent_path}')
    print(sdg_sentiment.to_string(index=False))

    sdg_kendall = compute_sdg_kendall(sdg_sentiment, rostat)
    sdg_kendall_path = OUTPUT_DIR / 'experimental_sdg_specific_kendall.csv'
    sdg_kendall.to_csv(sdg_kendall_path, index=False, float_format='%.4f')
    print(f'\nSDG-specific Kendall: {sdg_kendall_path}')
    print(sdg_kendall.to_string(index=False))


if __name__ == '__main__':
    main()
