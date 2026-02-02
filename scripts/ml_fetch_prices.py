#!/usr/bin/env python3
"""
Busca preços dos produtos no ML e atualiza o mapeamento com preços
"""

import json
import requests
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / 'config_mercadolivre.json'
MAP_FILE = Path(__file__).parent.parent / 'ml_products_map.json'
ML_API_URL = 'https://api.mercadolibre.com'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_map():
    with open(MAP_FILE, 'r') as f:
        return json.load(f)

def save_map(data):
    with open(MAP_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    config = load_config()
    headers = {
        'Authorization': f"Bearer {config['access_token']}",
        'Content-Type': 'application/json'
    }

    ml_map = load_map()
    print(f"Total de produtos no mapa: {len(ml_map)}")

    # Coleta todos os ml_ids
    items_to_fetch = []
    for sku, data in ml_map.items():
        if data.get('status') == 'active':
            ml_id = data.get('ml_id', '').replace('-', '')
            if ml_id:
                items_to_fetch.append((sku, ml_id))

    print(f"Produtos ativos para buscar preço: {len(items_to_fetch)}")

    # Busca em lotes de 20 (limite da API multiget)
    updated = 0
    batch_size = 20

    for i in range(0, len(items_to_fetch), batch_size):
        batch = items_to_fetch[i:i+batch_size]
        ids = ','.join([item[1] for item in batch])

        try:
            r = requests.get(
                f'{ML_API_URL}/items?ids={ids}&attributes=id,price,original_price,status,condition',
                headers=headers,
                timeout=30
            )

            if r.status_code == 200:
                results = r.json()

                for result in results:
                    if result.get('code') == 200:
                        item = result.get('body', {})
                        item_id = item.get('id', '').replace('-', '')

                        # Encontra o SKU correspondente
                        for sku, ml_id in batch:
                            if ml_id == item_id:
                                ml_map[sku]['price'] = item.get('price')
                                ml_map[sku]['original_price'] = item.get('original_price')
                                ml_map[sku]['condition'] = item.get('condition', 'new')
                                updated += 1
                                break

                if (i + batch_size) % 200 == 0:
                    print(f"  Processados: {min(i + batch_size, len(items_to_fetch))}/{len(items_to_fetch)}")

        except Exception as e:
            print(f"  Erro no lote {i}: {e}")

    save_map(ml_map)
    print(f"\nAtualizado! {updated} produtos com preço")

if __name__ == '__main__':
    main()
