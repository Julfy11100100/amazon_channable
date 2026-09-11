# WB → Channable feed generator

Скрипт формирует JSON-фид для Channable/Amazon.ae по карточкам Wildberries. Он использует штрихкоды из `constants.py`, получает товарные данные из Elasticsearch и переводит русскоязычные поля через локальный сервис перевода.

## Возможности

- Создаёт или дополняет `feed.json`, не генерируя уже добавленные товары повторно.
- Создаёт резервную копию фида перед обновлением.
- Добавляет GTIN, размеры, вес, OEM-коды, гарантию, совместимость с автомобилями и до семи изображений.
- Импортирует новые пары «артикул — GTIN» из Excel.

## Установка

Нужен Python 3.11+ и доступ к Elasticsearch и сервису перевода.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Заполните секреты в `.env`: `ES_PASSWORD` и `TRANSLATOR_API_KEY`. Файл `.env` не попадает в Git; для безопасной передачи структуры настроек используйте `.env.example`.

## Настройки

Все параметры считываются через `pydantic-settings` из переменных окружения, а при их отсутствии — из `.env`. Переменные окружения имеют приоритет над `.env`.

| Переменная | Назначение |
| --- | --- |
| `ES_HOST`, `ES_INDEX`, `ES_INDEX_IMAGES` | Подключение и индексы Elasticsearch |
| `ES_USER`, `ES_PASSWORD` | Учётные данные Elasticsearch |
| `TRANSLATOR_URL`, `TRANSLATOR_API_KEY` | Адрес и ключ сервиса перевода |
| `OUTPUT_FILE` | Имя выходного JSON-файла |
| `STORE_BASE_URL`, `CURRENCY` | Параметры товарных ссылок и цены |
| `TRANSLATOR_TARGET_LANG`, `TRANSLATOR_RETRIES`, `TRANSLATOR_RETRY_DELAY` | Параметры перевода и повторных попыток |
| `DEFAULT_WARRANTY` | Гарантия, если её нет в источнике |

## Запуск генератора

```powershell
python wb_to_channable_feed.py
```

Программа читает `constants.py`, запрашивает новые товары и сохраняет итог в `OUTPUT_FILE`. При существующем фиде перед записью создаётся файл вида `feed_YYYYMMDD_HHMM.json`.

## Импорт GTIN из Excel

В Excel должны быть две колонки без обязательной строки заголовков: в первой — GTIN, во второй — артикул. Данные будут добавлены или обновлены в словаре `BARCODES` файла `constants.py`.

```powershell
python xlsx_to_constants.py data\GTIN.xlsx
```
