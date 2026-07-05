# 🧠 Тренажер Мышления (Mishlenie)

Telegram-бот для развития 7 видов мышления и осознанности через интерактивные задания с обратной связью от ИИ.

## 🎯 Возможности

- **7 видов мышления:** аналитическое, логическое, критическое, системное, стратегическое, креативное, эмоциональный интеллект
- **5 фаз тренировки:** диагностика → погружение → обратная связь → комбинированные задания → интеграция осознанности
- **AI-коуч на базе DeepSeek:** персонализированные задания и обратная связь
- **Адаптивная сложность:** от бытовых сценариев до многоуровневых абстрактных задач
- **12 упражнений на осознанность** между тренировочными блоками
- **Профиль мышления** с визуальной шкалой и отслеживанием прогресса

## 🚀 Быстрый старт

### 1. Клонирование и установка

```bash
cd Mishlenie
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

### 2. Настройка

Создайте файл `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

Заполните переменные:
- `TELEGRAM_BOT_TOKEN` — токен бота от [@BotFather](https://t.me/BotFather)
- `DEEPSEEK_API_KEY` — API-ключ от [DeepSeek Platform](https://platform.deepseek.com/)

### 3. Запуск

```bash
python -m bot.main
```

## 🏗️ Структура проекта

```
Mishlenie/
├── bot/                    # Telegram-бот
│   ├── main.py             # Точка входа
│   ├── handlers/           # Обработчики по фазам
│   │   ├── start.py        # /start, приветствие, диагностика
│   │   ├── training.py     # Задания по видам мышления
│   │   ├── feedback.py     # Обратная связь
│   │   ├── combined.py     # Комбинированные задания
│   │   └── mindfulness.py  # Упражнения на осознанность
│   ├── keyboards.py        # Inline-клавиатуры
│   └── states.py           # FSM состояния
├── core/                   # Ядро
│   ├── config.py           # Настройки
│   ├── database.py         # Подключение к БД
│   └── models.py           # ORM модели
├── services/               # Бизнес-логика
│   ├── ai_service.py       # DeepSeek API клиент
│   ├── profile_service.py  # Профили мышления
│   └── progress_service.py # Прогресс и статистика
├── prompts/                # Промпты
│   ├── system_prompt.py    # Системный промпт
│   └── templates.py        # Шаблоны для фаз
├── requirements.txt
└── README.md
```

## 🔑 Технологии

- **aiogram 3.x** — Telegram Bot API
- **DeepSeek API** — AI-модели (chat + reasoner)
- **SQLite + SQLAlchemy** — база данных
- **Pydantic v2** — валидация конфигурации

## 📊 Модели DeepSeek

| Модель | Использование |
|--------|--------------|
| `deepseek-chat` | Обычные задания (фазы 1-3) |
| `deepseek-reasoner` | Комбинированные задания (фаза 4) |

## 📝 Лицензия

MIT
