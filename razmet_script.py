import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix
import os

# Увеличенные настройки шрифтов
LABEL_FONT_SIZE = 18
TITLE_FONT_SIZE = 22  # Еще больше увеличил для заголовков
ANNOTATION_FONT_SIZE = 16
SUPTITLE_FONT_SIZE = 24

# Загрузка данных
excel_path = 'комбинация_размет.xlsx'
data = pd.read_excel(excel_path, header=None)
data_cleaned = data.dropna()

# Создаем фигуру с увеличенной высотой
plt.figure(figsize=(12, 20))  # Увеличил высоту с 16 до 20

# Первая матрица (kartaslovcent)
ax1 = plt.subplot(2, 1, 1)
cm_kartaslov = confusion_matrix(data_cleaned[1], data_cleaned[2])
sns.heatmap(cm_kartaslov, annot=True, fmt='d', cmap='Blues', cbar=False,
            annot_kws={'size': ANNOTATION_FONT_SIZE, 'weight': 'bold'},
            linewidths=0.5, linecolor='gray')
plt.title('kartaslovcent', fontsize=TITLE_FONT_SIZE, pad=30)  # Увеличил pad
plt.xlabel('Предсказанные', fontsize=LABEL_FONT_SIZE, labelpad=20)
plt.ylabel('Фактические', fontsize=LABEL_FONT_SIZE, labelpad=20)

# Вторая матрица (RuSentiLex) с дополнительным отступом сверху
ax2 = plt.subplot(2, 1, 2)
cm_rusentilex = confusion_matrix(data_cleaned[1], data_cleaned[3])
sns.heatmap(cm_rusentilex, annot=True, fmt='d', cmap='Oranges', cbar=False,
            annot_kws={'size': ANNOTATION_FONT_SIZE, 'weight': 'bold'},
            linewidths=0.5, linecolor='gray')
plt.title('RuSentiLex', fontsize=TITLE_FONT_SIZE, pad=30)  # Увеличил pad
plt.xlabel('Предсказанные', fontsize=LABEL_FONT_SIZE, labelpad=20)
plt.ylabel('Фактические', fontsize=LABEL_FONT_SIZE, labelpad=20)

# Дополнительная регулировка расстояний
plt.subplots_adjust(hspace=1)  # Увеличивает вертикальное расстояние между графиками

# Сохранение с увеличенным DPI
output_path = os.path.join('.', 'vertical_confusion_matrices_fixed.png')
plt.savefig(output_path, bbox_inches='tight', dpi=300)
plt.show()
print(f'Исправленные матрицы сохранены в: {output_path}')