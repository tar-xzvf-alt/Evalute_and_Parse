import pandas as pd
import re
import pymorphy3
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import (accuracy_score, precision_score,
                             recall_score, f1_score, confusion_matrix,
                             classification_report)
import seaborn as sns
import matplotlib.pyplot as plt
import joblib
from string import punctuation
from nltk.corpus import stopwords
import nltk

morph = pymorphy3.MorphAnalyzer()



# 1. Функция предобработки текста с обработкой пропусков
def preprocess_text(text):
    if pd.isna(text):
        return ""

    # Приведение к нижнему регистру
    text = str(text).lower()

    # Удаление спецсимволов и цифр
    text = re.sub(r'[^а-яё\s]', '', text, flags=re.IGNORECASE)

    # Удаление пунктуации
    text = re.sub(r'[{}]'.format(re.escape(punctuation)), ' ', text)

    # Удаление лишних пробелов
    text = re.sub(r'\s+', ' ', text).strip()

    # Токенизация и лемматизация
    tokens = text.split()
    lemmas = []
    for token in tokens:
        if token not in russian_stopwords and len(token) > 3:
            lemma = morph.parse(token)[0].normal_form
            lemmas.append(lemma)

    return ' '.join(lemmas)


# 2. Функция загрузки и очистки данных
import pandas as pd
import chardet


def evaluate_model(y_true, y_pred, model_name, classes):
    print(f"\nОценка модели {model_name}:")
    print(classification_report(y_true, y_pred, zero_division=0))

    # Метрики
    metrics = {
        "Accuracy": accuracy_score(y_true, y_pred),
        "Precision": precision_score(y_true, y_pred, average='weighted', zero_division=0),
        "Recall": recall_score(y_true, y_pred, average='weighted'),
        "F1-score": f1_score(y_true, y_pred, average='weighted')
    }

    # Матрица ошибок
    cm = confusion_matrix(y_true, y_pred)

    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                xticklabels=classes,
                yticklabels=classes)
    plt.title(f'Матрица ошибок ({model_name})')
    plt.xlabel('Предсказание')
    plt.ylabel('Истинный класс')
    plt.show()

    return metrics


def load_and_clean_data(file_path):
    try:
        # Определяем тип файла по расширению
        if file_path.endswith(('.xlsx', '.xls')):
            # Чтение Excel файла
            df = pd.read_excel(file_path)

            # Выбираем только первые две колонки
            if len(df.columns) >= 2:
                df = df.iloc[:, :2]
                df.columns = ['sentiment', 'text']
            else:
                raise ValueError("Excel файл должен содержать минимум 2 колонки")

        elif file_path.endswith('.csv'):
            # Определение кодировки
            def detect_file_encoding(file_path):
                with open(file_path, 'rb') as f:
                    result = chardet.detect(f.read(10000))  # Анализируем первые 10KB
                return result['encoding']

            encoding = detect_file_encoding(file_path)

            # Чтение CSV файла
            try:
                # Пытаемся прочитать с автоматическим определением разделителя
                df = pd.read_csv(file_path, encoding=encoding, on_bad_lines='warn')

                # Выбираем первые две колонки
                if len(df.columns) >= 2:
                    df = df.iloc[:, :2]
                    df.columns = ['sentiment', 'text']
                else:
                    raise ValueError("CSV файл должен содержать минимум 2 колонки")

                # Удаление кавычек, если они есть
                df['text'] = df['text'].str.replace('"', '')

            except Exception as e:
                print(f"Ошибка чтения CSV: {e}")
                # Альтернативный метод чтения для сложных случаев
                with open(file_path, 'r', encoding=encoding) as f:
                    lines = [line.strip().split(',') for line in f.readlines()]

                # Создаем DataFrame из первых двух колонок
                df = pd.DataFrame(lines)[[0, 1]]
                df.columns = ['sentiment', 'text']
                df['text'] = df['text'].str.replace('"', '')
        else:
            raise ValueError("Неподдерживаемый формат файла. Используйте .xlsx, .xls или .csv")

        # Проверка и очистка данных
        print(f"\nДанные из {file_path} до обработки:")
        print(df.head())

        # Удаление строк с пропущенными значениями
        df = df.dropna()

        # Проверка на пустые строки после удаления
        if df.empty:
            raise ValueError("Файл не содержит данных после удаления пропусков")

        # Очистка и нормализация данных
        df['sentiment'] = df['sentiment'].astype(str).str.strip().str.lower()
        df['text'] = df['text'].astype(str).str.strip()

        # Удаление пустых текстов
        df = df[df['text'] != '']

        # Проверка допустимых значений sentiment
        valid_sentiments = ['positive', 'negative']
        if not df['sentiment'].isin(valid_sentiments).all():
            # Автокоррекция распространенных вариантов
            sentiment_mapping = {
                'pos': 'positive',
                'neg': 'negative',
                '1': 'positive',
                '0': 'negative',
                '1.0': 'positive',
                '0.0': 'negative'
            }

            df['sentiment'] = df['sentiment'].map(sentiment_mapping).fillna(df['sentiment'])

            # Повторная проверка
            invalid = set(df['sentiment']) - set(valid_sentiments)
            if invalid:
                raise ValueError(f"Недопустимые значения sentiment: {invalid}. Ожидается 'positive' или 'negative'")

        print("\nДанные после обработки:")
        print(df.head())
        print(f"\nВсего загружено записей: {len(df)}")

        return df

    except Exception as e:
        print(f"\nКритическая ошибка при загрузке {file_path}: {e}")
        exit()


# Инициализация лемматизатора и стоп-слов
nltk.download('stopwords')
russian_stopwords = stopwords.words('russian')

# 3. Загрузка и предобработка обучающих данных
train_df = load_and_clean_data('combcombcomb.xlsx')

temp = train_df.iloc[:, 1]

train_df['processed_text'] = temp.apply(preprocess_text)
train_df = train_df[train_df['processed_text'] != ""]  # Удаляем пустые тексты после обработки

print("\nОбучающие данные после обработки:")
print(train_df[[train_df.columns[0], 'processed_text', train_df.columns[1]]].head())

# 4. Подготовка данных для обучения
X_train = train_df['processed_text']
y_train = train_df.iloc[:, 0]

# Векторизация текста
vectorizer = TfidfVectorizer(max_features=5000)
X_train_vec = vectorizer.fit_transform(X_train)

# 5. Обучение моделей
print("\nОбучение моделей...")
models = {
    "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
    "KNN": KNeighborsClassifier(n_neighbors=5)
}

for name, model in models.items():
    model.fit(X_train_vec, y_train)
    print(f"{name} обучен")

# 6. Сохранение моделей и векторизатора
joblib.dump(models["Random Forest"], 'random_forest_model.pkl')
joblib.dump(models["KNN"], 'knn_model.pkl')
joblib.dump(vectorizer, 'tfidf_vectorizer.pkl')
print("\nМодели и векторизатор сохранены")

# 7. Загрузка и обработка тестовых данных
test_df = load_and_clean_data('comb_test_1.xlsx')
test_df['processed_text'] = test_df.iloc[:, 1].apply(preprocess_text)
test_df = test_df[test_df['processed_text'] != ""]  # Удаляем пустые тексты после обработки

print("\nТестовые данные после обработки:")
print(test_df[[test_df.columns[0], 'processed_text', test_df.columns[1]]].head())

X_test = test_df['processed_text']
y_test = test_df.iloc[:, 0]

# 8. Применение моделей на тестовых данных
X_test_vec = vectorizer.transform(X_test)

print("\nПредсказания на тестовых данных:")
results = {}
for name, model in models.items():
    y_pred = model.predict(X_test_vec)
    results[name] = {
        'predictions': y_pred,
        'true_labels': y_test
    }
    print(f"\n{name}:")
    print(pd.DataFrame({
        'Текст': test_df.iloc[:, 0],
        'Предсказание': y_pred,
        'Истинный класс': y_test
    }).head(10))

# 10. Оценка моделей
print("\nПодробная оценка моделей:")
metrics_results = {}
for name in models.keys():
    metrics_results[name] = evaluate_model(
        results[name]['true_labels'],
        results[name]['predictions'],
        name,
        models[name].classes_
    )

# 11. Сравнение моделей
print("\nСравнение моделей:")
metrics_df = pd.DataFrame(metrics_results).T
print(metrics_df)