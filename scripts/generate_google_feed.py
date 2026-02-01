#!/usr/bin/env python3
"""
Gera feed de produtos para Google Merchant Center
Formato: TSV (Tab Separated Values)
"""

import json
import csv
import os
from datetime import datetime

# Diretórios
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
PRODUCTS_FILE = os.path.join(PROJECT_DIR, "products.json")
OUTPUT_FILE = os.path.join(PROJECT_DIR, "google_merchant_feed.tsv")

# Configuração da loja
STORE_URL = "https://www.blumenauautomacao.com.br"
STORE_NAME = "Blumenau Automação"

# Campos obrigatórios do Google Merchant
GOOGLE_FIELDS = [
    "id",
    "title",
    "description",
    "link",
    "image_link",
    "availability",
    "price",
    "brand",
    "condition",
    "identifier_exists",
    "product_type",
]


def clean_text(text: str, max_length: int = None) -> str:
    """Limpa texto para o feed - remove tabs, newlines e caracteres problemáticos"""
    if not text:
        return ""
    # Remove tabs e newlines
    text = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    # Remove espaços múltiplos
    while "  " in text:
        text = text.replace("  ", " ")
    text = text.strip()
    # Limita tamanho se especificado
    if max_length and len(text) > max_length:
        text = text[:max_length-3] + "..."
    return text


def format_price(price: float) -> str:
    """Formata preço no padrão do Google: 123.45 BRL"""
    if not price or price <= 0:
        return ""
    return f"{price:.2f} BRL"


def get_availability(in_stock: bool) -> str:
    """Retorna disponibilidade no formato Google"""
    return "in_stock" if in_stock else "out_of_stock"


def build_product_link(slug: str) -> str:
    """Constrói link do produto no site"""
    return f"{STORE_URL}/produto.html?slug={slug}"


def convert_product(product: dict) -> dict:
    """Converte produto do formato interno para formato Google Merchant"""

    # Campos básicos
    product_id = product.get("id") or product.get("sku", "")
    title = clean_text(product.get("name", ""), max_length=150)
    description = clean_text(product.get("description", ""), max_length=5000)

    # Se não tem descrição, usa o título
    if not description:
        description = title

    # Link do produto
    slug = product.get("slug", "")
    link = build_product_link(slug) if slug else ""

    # Imagem
    image_link = product.get("image", "")

    # Preço e disponibilidade
    price = product.get("price", 0)
    in_stock = product.get("inStock", False)

    # Marca
    brand = clean_text(product.get("brand", ""), max_length=70)
    if not brand or brand.lower() in ["importado", "genérico", "generico"]:
        brand = "Importado"

    # Categoria (product_type)
    category_path = product.get("categoryPath", [])
    product_type = " > ".join(category_path) if category_path else ""

    return {
        "id": product_id,
        "title": title,
        "description": description,
        "link": link,
        "image_link": image_link,
        "availability": get_availability(in_stock),
        "price": format_price(price),
        "brand": brand,
        "condition": "new",
        "identifier_exists": "false",  # Produtos sem GTIN/MPN
        "product_type": product_type,
    }


def generate_feed():
    """Gera o feed TSV para Google Merchant"""

    print(f"Lendo produtos de {PRODUCTS_FILE}...")

    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", [])
    print(f"Total de produtos: {len(products)}")

    # Filtra produtos válidos (com preço, imagem e em estoque para Google Shopping)
    valid_products = []
    skipped = {"no_price": 0, "no_image": 0, "no_slug": 0, "out_of_stock": 0}

    for product in products:
        price = product.get("price", 0)
        image = product.get("image", "")
        slug = product.get("slug", "")
        in_stock = product.get("inStock", False)

        if not price or price <= 0:
            skipped["no_price"] += 1
            continue
        if not image:
            skipped["no_image"] += 1
            continue
        if not slug:
            skipped["no_slug"] += 1
            continue
        # Incluir produtos fora de estoque também (aparecerão como "out_of_stock")
        # if not in_stock:
        #     skipped["out_of_stock"] += 1
        #     continue

        valid_products.append(product)

    print(f"Produtos válidos para o feed: {len(valid_products)}")
    print(f"Ignorados: {skipped}")

    # Gera o arquivo TSV
    print(f"Gerando feed em {OUTPUT_FILE}...")

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GOOGLE_FIELDS, delimiter="\t")
        writer.writeheader()

        for product in valid_products:
            google_product = convert_product(product)
            writer.writerow(google_product)

    print(f"Feed gerado com sucesso!")
    print(f"Arquivo: {OUTPUT_FILE}")
    print(f"Tamanho: {os.path.getsize(OUTPUT_FILE) / 1024:.1f} KB")

    # Estatísticas
    in_stock_count = sum(1 for p in valid_products if p.get("inStock", False))
    out_of_stock_count = len(valid_products) - in_stock_count
    print(f"\nEstatísticas:")
    print(f"  Em estoque: {in_stock_count}")
    print(f"  Fora de estoque: {out_of_stock_count}")

    return OUTPUT_FILE


if __name__ == "__main__":
    generate_feed()
