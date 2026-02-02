#!/usr/bin/env python3
"""
Sincronização inteligente com Mercado Livre
- Compara produtos locais com ML
- Atualiza apenas o que mudou (preço, estoque)
- Usa scroll_id para pegar todos os itens
- Lida com rate limiting

Uso:
  python ml_sync.py              # Sincroniza preços e estoque
  python ml_sync.py --dry-run    # Simula sem alterar nada
"""

import json
import os
import sys
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime

# Configuração
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
PRODUCTS_FILE = ROOT_DIR / 'products.json'
ML_MAP_FILE = ROOT_DIR / 'ml_products_map.json'
CONFIG_FILE = ROOT_DIR / 'config_mercadolivre.json'

ML_API_URL = 'https://api.mercadolibre.com'

# Margem de preço para considerar mudança (evita updates desnecessários)
PRICE_TOLERANCE = 1.00  # R$ 1,00

# Taxa Mercado Livre (frete + comissão)
ML_SHIPPING = 25.0  # R$ 25 frete
ML_FEE_RATE = 0.18  # 18% taxa ML
MIN_MARKUP = 0.35   # 35% markup mínimo

# Taxa Mercado Pago no site (para calcular custo original)
MP_FEE_RATE = 0.0499


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}")


def load_config():
    """Carrega config do arquivo ou variáveis de ambiente"""
    # Tenta variáveis de ambiente primeiro (GitHub Actions)
    if os.environ.get('ML_ACCESS_TOKEN'):
        return {
            'access_token': os.environ['ML_ACCESS_TOKEN'],
            'refresh_token': os.environ.get('ML_REFRESH_TOKEN', ''),
            'app_id': os.environ.get('ML_APP_ID', ''),
            'secret_key': os.environ.get('ML_SECRET_KEY', ''),
            'user_id': os.environ.get('ML_USER_ID', '')
        }

    # Fallback para arquivo local
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)

    raise Exception("Configuração ML não encontrada")


def refresh_token(config):
    """Renova o access_token usando refresh_token"""
    log("Renovando token ML...")

    response = requests.post(f'{ML_API_URL}/oauth/token', data={
        'grant_type': 'refresh_token',
        'client_id': config['app_id'],
        'client_secret': config['secret_key'],
        'refresh_token': config['refresh_token']
    })

    if response.status_code == 200:
        data = response.json()
        config['access_token'] = data['access_token']
        config['refresh_token'] = data['refresh_token']

        # Salva no arquivo se existir
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

        log("Token renovado com sucesso")
        return True
    else:
        log(f"Erro ao renovar token: {response.text}")
        return False


def load_products():
    """Carrega produtos locais"""
    with open(PRODUCTS_FILE, 'r') as f:
        data = json.load(f)
    return {p.get('sku', p.get('id', '')): p for p in data.get('products', []) if p.get('sku') or p.get('id')}


def load_ml_map():
    """Carrega mapeamento ML"""
    if ML_MAP_FILE.exists():
        with open(ML_MAP_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_ml_map(ml_map):
    """Salva mapeamento ML"""
    with open(ML_MAP_FILE, 'w') as f:
        json.dump(ml_map, f, indent=2, ensure_ascii=False)


def calculate_ml_price(cost):
    """Calcula preço para ML com margem"""
    if not cost or cost <= 0:
        return None

    # Preço base = (custo + frete) / (1 - taxa ML)
    base_price = (cost + ML_SHIPPING) / (1 - ML_FEE_RATE)

    # Garante markup mínimo
    min_price = cost * (1 + MIN_MARKUP)

    return round(max(base_price, min_price), 2)


def fetch_ml_items(headers, item_ids):
    """Busca múltiplos itens do ML (multiget)"""
    if not item_ids:
        return {}

    results = {}
    batch_size = 20

    for i in range(0, len(item_ids), batch_size):
        batch = item_ids[i:i+batch_size]
        ids = ','.join(batch)

        try:
            r = requests.get(
                f'{ML_API_URL}/items?ids={ids}&attributes=id,price,available_quantity,status,seller_custom_field',
                headers=headers,
                timeout=30
            )

            if r.status_code == 200:
                for item in r.json():
                    if item.get('code') == 200:
                        body = item.get('body', {})
                        results[body['id']] = body

            time.sleep(0.1)  # Rate limiting

        except Exception as e:
            log(f"Erro ao buscar lote: {e}")

    return results


def update_ml_item(headers, item_id, updates):
    """Atualiza um item no ML"""
    try:
        r = requests.put(
            f'{ML_API_URL}/items/{item_id}',
            headers=headers,
            json=updates,
            timeout=15
        )
        return r.status_code == 200
    except:
        return False


def sync_products(dry_run=False):
    """Sincroniza produtos com ML"""
    log("=" * 60)
    log("SINCRONIZAÇÃO MERCADO LIVRE" + (" [DRY-RUN]" if dry_run else ""))
    log("=" * 60)

    # Carrega dados
    config = load_config()
    headers = {
        'Authorization': f"Bearer {config['access_token']}",
        'Content-Type': 'application/json'
    }

    # Testa token
    test = requests.get(f'{ML_API_URL}/users/me', headers=headers)
    if test.status_code == 401:
        if not refresh_token(config):
            log("ERRO: Não foi possível renovar token")
            sys.exit(1)
        headers['Authorization'] = f"Bearer {config['access_token']}"

    products = load_products()
    ml_map = load_ml_map()

    log(f"Produtos locais: {len(products)}")
    log(f"Produtos mapeados ML: {len(ml_map)}")

    # Coleta IDs do ML para buscar
    ml_ids_to_fetch = []
    sku_to_ml_id = {}

    for sku, ml_data in ml_map.items():
        if ml_data.get('status') == 'active' and ml_data.get('ml_id'):
            ml_id = ml_data['ml_id'].replace('-', '')
            ml_ids_to_fetch.append(ml_id)
            sku_to_ml_id[sku] = ml_id

    log(f"\nBuscando {len(ml_ids_to_fetch)} itens do ML...")
    ml_items = fetch_ml_items(headers, ml_ids_to_fetch)
    log(f"Itens retornados: {len(ml_items)}")

    # Compara e identifica mudanças
    stats = {'price_updates': 0, 'stock_updates': 0, 'errors': 0, 'skipped': 0}
    updates_to_make = []

    for sku, local_product in products.items():
        # Encontra no mapa (com e sem prefixo)
        ml_data = ml_map.get(sku)
        if not ml_data:
            sku_clean = sku.replace('LV-', '').replace('SE-', '')
            ml_data = ml_map.get(sku_clean)

        if not ml_data or ml_data.get('status') != 'active':
            continue

        ml_id = ml_data.get('ml_id', '').replace('-', '')
        ml_item = ml_items.get(ml_id)

        if not ml_item:
            continue

        # Calcula preço esperado para ML
        local_cost = local_product.get('price', 0)
        # O preço em products.json já inclui taxa MP, precisamos do custo original
        # custo = preco_site * (1 - 0.0499) aproximadamente
        original_cost = local_cost * 0.9501  # Remove taxa MP para ter o custo
        expected_ml_price = calculate_ml_price(original_cost)

        if not expected_ml_price:
            continue

        current_ml_price = ml_item.get('price', 0)

        # Verifica se precisa atualizar preço
        price_diff = abs(expected_ml_price - current_ml_price)

        updates = {}

        if price_diff > PRICE_TOLERANCE:
            updates['price'] = expected_ml_price
            stats['price_updates'] += 1

        # Verifica estoque
        local_in_stock = local_product.get('inStock', True)
        ml_quantity = ml_item.get('available_quantity', 0)

        if local_in_stock and ml_quantity == 0:
            updates['available_quantity'] = 10
            stats['stock_updates'] += 1
        elif not local_in_stock and ml_quantity > 0:
            updates['available_quantity'] = 0
            stats['stock_updates'] += 1

        if updates:
            updates_to_make.append((ml_id, sku, updates, current_ml_price, expected_ml_price))

    # Aplica atualizações
    log(f"\nAtualizações necessárias:")
    log(f"  Preços: {stats['price_updates']}")
    log(f"  Estoque: {stats['stock_updates']}")

    if updates_to_make:
        if dry_run:
            log(f"\n[DRY-RUN] {len(updates_to_make)} atualizações seriam feitas:")
            for i, (ml_id, sku, updates, old_price, new_price) in enumerate(updates_to_make[:20], 1):
                if 'price' in updates:
                    log(f"  [{i}] {sku}: R$ {old_price:.2f} → R$ {new_price:.2f}")
            if len(updates_to_make) > 20:
                log(f"  ... e mais {len(updates_to_make) - 20} atualizações")
        else:
            log(f"\nAplicando {len(updates_to_make)} atualizações...")

            for i, (ml_id, sku, updates, old_price, new_price) in enumerate(updates_to_make, 1):
                success = update_ml_item(headers, ml_id, updates)

                if success:
                    if 'price' in updates:
                        log(f"  [{i}] {sku}: R$ {old_price:.2f} → R$ {new_price:.2f}")
                        # Atualiza mapa com novo preço
                        for map_sku in [sku, sku.replace('LV-', '').replace('SE-', '')]:
                            if map_sku in ml_map:
                                ml_map[map_sku]['price'] = new_price
                else:
                    stats['errors'] += 1
                    log(f"  [{i}] ERRO: {sku}")

                time.sleep(0.2)  # Rate limiting

    # Salva mapa atualizado
    save_ml_map(ml_map)

    # Resumo
    log("\n" + "=" * 60)
    log("RESUMO")
    log("=" * 60)
    log(f"Preços atualizados: {stats['price_updates']}")
    log(f"Estoque atualizado: {stats['stock_updates']}")
    log(f"Erros: {stats['errors']}")

    return stats['errors'] == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sincroniza produtos com Mercado Livre')
    parser.add_argument('--dry-run', action='store_true', help='Simula sem fazer alterações')
    args = parser.parse_args()

    success = sync_products(dry_run=args.dry_run)
    sys.exit(0 if success else 1)
