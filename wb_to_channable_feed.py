#!/usr/bin/env python3
"""
WB → Channable feed generator for Amazon.ae
"""

import json
import re
import logging
from time import sleep

from elasticsearch import Elasticsearch
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
ES_HOST = "http://localhost:9200"
ES_INDEX = "wb_products_954e1027"
ES_INDEX_IMAGES = "npr_products_data"
ES_USER = "elastic"
ES_PASSWORD = "ElasticsearCH_Secure_Pass_2025!!!"

OUTPUT_FILE = "feed.json"

TRANSLATOR_URL = "http://localhost:8000/translator"
TRANSLATOR_API_KEY = "11100100"
TRANSLATOR_TARGET_LANG = "en"

DEFAULT_WARRANTY = "24"
DEFAULT_MATERIAL_TYPE = "Алюминий, Сталь, Резина, Медь, Пластик"

BARCODES: dict[str, str] = {
    "LCAC 0553": "6295157511132",
    "LCAC 0811": "6295157511125",
    "LCAC 0834": "6295157511118",
    "LCAC 0864": "6295157511101",
    "LCAC 0865": "6295157511095",
    "LCAC 08H1": "6295157511088",
    "LCAC 08L4": "6295157511071",
    "LCAC 08S5": "6295157511064",
    "LCAC 1100": "6295157511057",
    "LCAC 1104": "6295157511040",
    "LCAC 1162": "6295157511033",
}

STORE_BASE_URL = "https://yourstore.ae/products"
CURRENCY = "AED"

DESCRIPTION_STRIP_PHRASE = "Для проверки применяемости отправьте VIN автомобиля через вкладку Вопросы!"

# ─── TRANSLATOR ──────────────────────────────────────────────────────────────

def translate(text: str) -> str:
    if not text:
        return ""
    try:
        resp = requests.post(
            TRANSLATOR_URL,
            headers={"X-API-Key": TRANSLATOR_API_KEY, "Content-Type": "application/json"},
            json={"text": text, "target_language": TRANSLATOR_TARGET_LANG},
            timeout=30,
        )
        resp.raise_for_status()
        sleep(5)
        return resp.json().get("translated_text") or text
    except Exception as e:
        log.warning(f"Ошибка перевода '{text[:50]}...': {e}")
        return text


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def clean_description(text: str) -> str:
    if not text:
        return ""
    text = text.replace(DESCRIPTION_STRIP_PHRASE, "")
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r" {2,}", " ", text).strip()


def get_characteristic(characteristics: list, name: str) -> str:
    for c in characteristics:
        if c.get("name") == name:
            val = c.get("value")
            if isinstance(val, list):
                return ", ".join(str(v) for v in val)
            return str(val)
    return ""


def build_product_link(vendor_code: str, nm_id: int) -> str:
    slug = vendor_code.lower().replace(" ", "-")
    return f"{STORE_BASE_URL}/{slug}-{nm_id}"


# ─── IMAGES ──────────────────────────────────────────────────────────────────

def extract_image_number(url: str) -> int | None:
    match = re.search(r"/(\d+)\.jpg$", url, re.IGNORECASE)
    return int(match.group(1)) if match else None


def get_base_images(product_images: list[dict] | None) -> dict[int, str]:
    if not product_images:
        return {}
    result = {}
    for img in product_images:
        if img.get("IMAGE_PRODUCT_TYPE") == "BASE" and img.get("IMAGE_PRODUCT_LINK"):
            url = img["IMAGE_PRODUCT_LINK"]
            num = extract_image_number(url)
            if num is not None:
                result[num] = url
    return result


# ─── OEM / CARS ──────────────────────────────────────────────────────────────

def extract_oem_codes(oem_list: list[dict] | None) -> str:
    if not oem_list:
        return ""
    return "; ".join(
        item["OEM_CODE"] for item in oem_list if item.get("OEM_CODE")
    )


def deduplicate_models(cars: list[dict] | None) -> list[str]:
    """
    Уникальные модели без учёта регистра.
    iX35 и ix35 — одно и то же, оставляем первое вхождение.
    Берём MODEL_F (короткое имя без поколения), если нет — MODEL.
    """
    if not cars:
        return []
    seen_lower: set[str] = set()
    result: list[str] = []
    for car in cars:
        model = (car.get("MODEL_F") or car.get("MODEL", "")).strip()
        if not model:
            continue
        key = model.upper()
        if key not in seen_lower:
            seen_lower.add(key)
            result.append(model)
    return result


def deduplicate_marks(cars: list[dict] | None) -> list[str]:
    if not cars:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for car in cars:
        mark = car.get("MARK", "").strip()
        if mark and mark.upper() not in seen:
            seen.add(mark.upper())
            result.append(mark)
    return result


# ─── ASSEMBLITY HTML ─────────────────────────────────────────────────────────

ROW_TPL = (
    '<tr class="e75_3_4-a1">' +
    '<td class="e75_3_4-a2"><span class="RA-g6 RA-g7 RA-h3 RA-i0"><span>{mark}</span></span></td>' +
    '<td class="e75_3_4-a2"><span class="RA-g6 RA-g7 RA-h3 RA-i0"><span>{model}</span></span></td>' +
    '<td class="e75_3_4-a2"><span class="RA-g6 RA-g7 RA-h3 RA-i0"><span>{encode}</span></span></td>' +
    '<td class="e75_3_4-a2"><span class="RA-g6 RA-g7 RA-h3 RA-i0"><span>{period}</span></span></td>' +
    '<td class="e75_3_4-a2"><span class="RA-g6 RA-g7 RA-h3 RA-i0"><span>{volume}</span></span></td>' +
    '</tr>'
)


def build_assemblity_html(cars: list[dict] | None) -> str:
    if not cars:
        return ""
    rows = []
    for car in cars:
        mark   = car.get("MARK", "")
        model  = car.get("MODEL", "")
        encode = car.get("ENCODE", "")
        start  = (car.get("START") or "")[:4]
        finish = (car.get("FINISH") or "")[:4]
        period = f"{start} - {finish}" if finish else f"{start} - present"
        volume = str(car.get("ENGINEVOLUME_L", ""))
        rows.append(ROW_TPL.format(
            mark=mark, model=model, encode=encode, period=period, volume=volume
        ))
    return "<tbody>" + "".join(rows) + "</tbody>"


# ─── ELASTICSEARCH ───────────────────────────────────────────────────────────

def fetch_all_docs(es: Elasticsearch, index: str) -> list[dict]:
    result = []
    resp = es.search(index=index, scroll="2m", size=500, body={"query": {"match_all": {}}})
    scroll_id = resp["_scroll_id"]
    while True:
        hits = resp["hits"]["hits"]
        if not hits:
            break
        for hit in hits:
            result.append(hit["_source"])
        resp = es.scroll(scroll_id=scroll_id, scroll="2m")
    es.clear_scroll(scroll_id=scroll_id)
    return result


def fetch_npr_data_by_codes(es: Elasticsearch, codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    resp = es.search(
        index=ES_INDEX_IMAGES,
        size=len(codes),
        body={
            "query": {"terms": {"code": codes}},
            "_source": ["code", "product_images", "oem", "cars_new", "garant_val"],
        },
    )
    return {
        hit["_source"]["code"]: hit["_source"]
        for hit in resp["hits"]["hits"]
        if hit["_source"].get("code")
    }


# ─── MAIN CONVERTER ──────────────────────────────────────────────────────────

def kg_to_g(val: str | float) -> str:
    try:
        return str(int(float(val) * 1000))
    except (ValueError, TypeError):
        return ""


def cm_to_mm(val) -> str:
    try:
        return str(int(float(val) * 10))
    except (ValueError, TypeError):
        return ""


def wb_doc_to_feed_item(doc: dict, barcode_map: dict, npr_map: dict) -> dict | None:
    vendor_code = doc.get("vendorCode", "").strip()
    if vendor_code not in barcode_map:
        return None

    ean = barcode_map[vendor_code]
    nm_id = doc.get("nmID", "")
    characteristics = doc.get("characteristics", [])
    dimensions = doc.get("dimensions", {})

    # ── NPR данные ──────────────────────────────────────────────────────────
    npr = npr_map.get(vendor_code, {})

    images_by_num = get_base_images(npr.get("product_images"))
    sorted_nums = sorted(images_by_num.keys())
    images_ordered = [images_by_num[n] for n in sorted_nums]

    oem_string = extract_oem_codes(npr.get("oem"))
    cars = npr.get("cars_new") or []
    car_marks = deduplicate_marks(cars)
    car_models = deduplicate_models(cars)
    assemblity_html = build_assemblity_html(cars)

    garant_val = npr.get("garant_val")
    warranty = str(garant_val) if garant_val is not None else DEFAULT_WARRANTY

    # ── Характеристики WB ───────────────────────────────────────────────────
    country_raw      = get_characteristic(characteristics, "Страна производства")
    weight_kg        = get_characteristic(characteristics, "Вес без упаковки (кг)")
    manuf_article    = get_characteristic(characteristics, "Артикул производителя")

    # ── Переводы ────────────────────────────────────────────────────────────
    log.info(f"Переводим: {vendor_code}")

    title_en            = translate(doc.get("title", ""))
    description_en_text = translate(clean_description(doc.get("description", "")))
    description_en_html = f"<p>{description_en_text}</p>" if description_en_text else ""
    product_type_en     = translate(doc.get("subjectName", ""))
    country_en          = translate(country_raw)

    # ── Сборка объекта — только поля из Excel ───────────────────────────────
    item: dict = {
        "id":                       vendor_code,
        "gtin":                     ean,
        "brand":                    doc.get("brand", ""),
        "mpn":                      manuf_article or vendor_code,
        "title":                    title_en,
        "description":              description_en_html,
        "product_type":             product_type_en,
        "country_of_origin":        country_en,
        "link":                     build_product_link(vendor_code, nm_id),
        "price":                    f"0.00 {CURRENCY}",
        "availability":             "out of stock",
        "condition":                "new",
        "item_group_id":            str(doc.get("imtID", "")),
        "product_weight":           kg_to_g(weight_kg),
        "shipping_weight":          kg_to_g(dimensions.get("weightBrutto", "")),
        "product_length":           cm_to_mm(dimensions.get("length")),
        "product_width":            cm_to_mm(dimensions.get("width")),
        "product_height":           cm_to_mm(dimensions.get("height")),
        "OEM":                      oem_string,
        "Key Product Features":     oem_string,
        "Manufacturer":             doc.get("brand", ""),
        "Manufacturer Part Number": manuf_article or vendor_code,
        "Quantity":                 0,
        "Warranty":                 warranty,
        "Assemblity_description":   assemblity_html,
        "Material Type":            DEFAULT_MATERIAL_TYPE
    }

    # Фотографии image_link-1 … image_link-7
    for i, url in enumerate(images_ordered[:7], start=1):
        item[f"image_link-{i}"] = url

    # CAR_MARKA: одна — CAR_MARKA, несколько — CAR_MARKA_1, CAR_MARKA_2 …
    if len(car_marks) == 1:
        item["CAR_MARKA"] = car_marks[0]
    elif len(car_marks) > 1:
        for i, mark in enumerate(car_marks, start=1):
            item[f"CAR_MARKA_{i}"] = mark

    # CAR_MODEL: одна — CAR_MODEL, несколько — CAR_MODEL_1, CAR_MODEL_2 …
    if len(car_models) == 1:
        item["CAR_MODEL"] = car_models[0]
    elif len(car_models) > 1:
        for i, model in enumerate(car_models, start=1):
            item[f"CAR_MODEL_{i}"] = model

    # Убираем пустые строки (кроме Quantity — он должен быть 0)
    return {k: v for k, v in item.items() if v != "" and v is not None or k == "Quantity"}


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def main():
    es = Elasticsearch(ES_HOST, basic_auth=(ES_USER, ES_PASSWORD))
    log.info(f"ES: {ES_HOST} / {ES_INDEX}")

    docs = fetch_all_docs(es, ES_INDEX)
    log.info(f"WB документов: {len(docs)}")

    npr_map = fetch_npr_data_by_codes(es, list(BARCODES.keys()))
    log.info(f"NPR найдено: {len(npr_map)}")

    feed = []
    for doc in docs:
        item = wb_doc_to_feed_item(doc, BARCODES, npr_map)
        if item:
            feed.append(item)

    log.info(f"Товаров в фиде: {len(feed)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)

    log.info(f"Сохранено: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
