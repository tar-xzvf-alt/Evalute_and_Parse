# coding: utf-8
"""Merge Rosstat indicators with SDG analysis results. Kendall tau correlations + panel FE regression."""
import os
import pandas as pd
import numpy as np
from scipy.stats import kendalltau
import statsmodels.api as sm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROSTAT_PATH = 'data/region_stats/region_indicators.csv'
SDG_DIST_PATH = 'data/sdg_category_analysis/sdg_category_distribution_20260524_190250.xlsx'
SDG_SENT_PATH = 'data/sdg_sentiment_analysis/sdg_sentiment_by_category_20260524_214856.xlsx'
OUTPUT_DIR = 'data/correlation_analysis'

def panel_fe_regression(data, y_col, x_col):
    """Entity fixed-effects panel regression: y_it = alpha_i + beta * x_it + eps_it.
    Returns (coef, p_value, r2_within, n_obs)."""
    df = data[['region', 'year', y_col, x_col]].dropna().copy()
    if len(df) < 6:
        return None
    # Entity dummies
    dummies = pd.get_dummies(df['region'], drop_first=True, dtype=float)
    X = pd.concat([df[[x_col]], dummies], axis=1)
    X = sm.add_constant(X, has_constant='add')
    y = df[y_col]
    try:
        model = sm.OLS(y, X).fit()
        coef = model.params[x_col]
        pval = model.pvalues[x_col]
        r2 = model.rsquared
        return (coef, pval, r2, len(df))
    except Exception:
        return None

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    rostat = pd.read_csv(ROSTAT_PATH)
    sdg_dist = pd.read_excel(SDG_DIST_PATH)
    sdg_sent = pd.read_excel(SDG_SENT_PATH)

    # --- Compute per-capita indicators ---
    rostat['retail_trade_per_capita'] = rostat['retail_trade'] * 1e6 / (rostat['population'] * 1e3)
    rostat['environmental_spending_per_capita'] = rostat['environmental_spending'] * 1e6 / (rostat['population'] * 1e3)

    # --- Merge: Rosstat + distribution ---
    dist_cols = ['region', 'year', 'Социальные_pct', 'Экономические_pct', 'Экологические_pct', 'total']
    merged_dist = sdg_dist[dist_cols].merge(rostat, on=['region', 'year'], how='inner')

    # --- Merge: Rosstat + sentiment (kartaslovsent) ---
    sent_k = sdg_sent[sdg_sent['dictionary'] == 'kartaslovsent'].pivot_table(
        index=['region', 'year'], columns='category', values='positive_pct'
    ).reset_index()
    sent_k = sent_k.rename(columns={
        'Социальные': 'pos_social',
        'Экономические': 'pos_economic',
        'Экологические': 'pos_environmental',
    })
    merged_sent = sent_k.merge(rostat, on=['region', 'year'], how='inner')

    # --- Merge all ---
    merged = merged_dist.merge(
        merged_sent[['region', 'year', 'pos_social', 'pos_economic', 'pos_environmental']],
        on=['region', 'year'], how='inner'
    )
    merged = merged[(merged['year'] >= 2020) & (merged['year'] <= 2023)]
    merged.to_csv(os.path.join(OUTPUT_DIR, 'merged_data.csv'), index=False, float_format='%.2f')
    print('Объединённые данные (12 строк, 2020-2023):')
    print(merged[['region', 'year', 'pos_economic', 'grp_per_capita', 'unemployment_pct']].to_string(index=False))

    # === Kendall tau correlations ===
    rostat_indicators = [
        # Social
        ('unemployment_pct',              'Уровень безработицы, %'),
        ('birth_rate',                    'Коэффициент рождаемости'),
        ('deaths_per_100k',              'Смертность на 100 тыс.'),
        ('doctors_per_10k',              'Врачей на 10 тыс.'),
        ('hospital_beds_per_10k',        'Коек на 10 тыс.'),
        # Economic
        ('grp_per_capita',               'ВРП на душу, руб.'),
        ('investment_per_capita',        'Инвестиции на душу, руб.'),
        ('average_monthly_wage',         'Среднемесячная зарплата, руб.'),
        ('retail_trade_per_capita',      'Оборот розницы на душу, руб.'),
        # Environmental
        ('emissions_thousand_tons',      'Выбросы в атмосферу, тыс. т'),
        ('captured_pollutants_pct',      'Доля уловленных веществ, %'),
        ('fresh_water_use',              'Забор свежей воды, млн м³'),
        ('polluted_wastewater',          'Сброс стоков, млн м³'),
        ('environmental_spending_per_capita', 'Расходы на охрану среды на душу, руб.'),
    ]

    our_metrics = [
        ('Социальные_pct',       'Доля социальной категории, %'),
        ('Экономические_pct',    'Доля экономической категории, %'),
        ('Экологические_pct',    'Доля экологической категории, %'),
        ('pos_economic',         'Позитивность экономической, %'),
        ('pos_social',           'Позитивность социальной, %'),
        ('pos_environmental',    'Позитивность экологической, %'),
    ]

    corr_results = []
    for metric, metric_name in our_metrics:
        for ind, ind_name in rostat_indicators:
            subset = merged[[metric, ind]].dropna()
            if len(subset) < 3:
                continue
            tau, pval = kendalltau(subset[metric], subset[ind])
            corr_results.append({
                'Характеристика повестки': metric_name,
                'Показатель Росстата': ind_name,
                'kendall_tau': round(tau, 3),
                'p_value': round(pval, 4),
                'n': len(subset),
            })

    corr_df = pd.DataFrame(corr_results)
    corr_df = corr_df.sort_values('kendall_tau', key=abs, ascending=False)
    corr_path = os.path.join(OUTPUT_DIR, 'correlations.csv')
    corr_df.to_csv(corr_path, index=False, float_format='%.3f')
    print(f'\nКорреляции Кендалла сохранены: {corr_path}')
    top = corr_df[abs(corr_df['kendall_tau']) > 0.3]
    print(top.to_string(index=False))

    # === Panel FE regression ===
    reg_pairs = [
        ('pos_economic',      'grp_per_capita'),
        ('pos_economic',      'investment_per_capita'),
        ('pos_social',        'unemployment_pct'),
        ('pos_social',        'grp_per_capita'),
        ('pos_environmental', 'emissions_thousand_tons'),
        ('Экологические_pct',  'grp_per_capita'),
        ('Социальные_pct',    'unemployment_pct'),
        ('Экономические_pct', 'investment_per_capita'),
    ]

    print('\n=== Панельная регрессия (FE по регионам, n=12) ===')
    reg_results = []
    for y_col, x_col in reg_pairs:
        res = panel_fe_regression(merged, y_col, x_col)
        if res:
            coef, pval, r2, n = res
            reg_results.append({
                'Зависимая': y_col,
                'Независимая': x_col,
                'Коэфф': round(coef, 4),
                'p-value': round(pval, 4),
                'R²': round(r2, 3),
                'n': n,
            })
            sig = '**' if pval < 0.05 else ('*' if pval < 0.1 else '')
            print(f'  {y_col} ~ {x_col}: beta={coef:.4f} (p={pval:.4f}){sig} R2={r2:.3f} n={n}')

    reg_df = pd.DataFrame(reg_results)
    reg_path = os.path.join(OUTPUT_DIR, 'panel_regressions.csv')
    reg_df.to_csv(reg_path, index=False, float_format='%.4f')
    print(f'\nРегрессии сохранены: {reg_path}')

    # === Scatter plots (key pairs) ===
    pairs = [
        ('grp_per_capita', 'pos_economic', 'ВРП на душу vs экономическая позитивность'),
        ('unemployment_pct', 'pos_social', 'Безработица vs социальная позитивность'),
        ('emissions_thousand_tons', 'pos_environmental', 'Выбросы vs экологическая позитивность'),
        ('grp_per_capita', 'Экологические_pct', 'ВРП на душу vs доля экол. категории'),
        ('investment_per_capita', 'pos_economic', 'Инвестиции на душу vs экон. позитивность'),
    ]

    colors = {'Астраханская область': '#FF9800', 'Омская область': '#2196F3', 'Татарстан': '#4CAF50'}
    for x_col, y_col, title in pairs:
        subset = merged[[x_col, y_col, 'region', 'year']].dropna()
        if len(subset) < 3:
            continue
        fig, ax = plt.subplots(figsize=(8, 6))
        for reg in subset['region'].unique():
            rdf = subset[subset['region'] == reg]
            ax.scatter(rdf[x_col], rdf[y_col], c=colors.get(reg, '#999'),
                       label=reg, s=80, edgecolors='black', linewidth=0.5)
            for _, row in rdf.iterrows():
                ax.annotate(str(int(row['year'])), (row[x_col], row[y_col]),
                            textcoords='offset points', xytext=(5, 5), fontsize=8)

        if len(subset) >= 3:
            tau, _ = kendalltau(subset[x_col], subset[y_col])
            ax.set_title(f'{title}\nKendall tau = {tau:.2f}')
        ax.set_xlabel(x_col.replace('_', ' ').title())
        ax.set_ylabel(y_col.replace('_', ' ').title())
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        safe_name = title.replace(' ', '_').replace('/', '_')
        plt.savefig(os.path.join(OUTPUT_DIR, f'{safe_name}.png'), dpi=150)
        plt.close()
        print(f'  График: {safe_name}.png')

    print(f'\nГотово. Результаты в: {OUTPUT_DIR}/')

if __name__ == '__main__':
    main()
