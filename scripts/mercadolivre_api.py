#!/usr/bin/env python3
"""
Blumenau Automação - Integração Mercado Livre via API

Este script cria anúncios no Mercado Livre automaticamente usando a API oficial.
Calcula preços para lucro zero (cobrindo taxas ML).

SETUP INICIAL:
1. Acesse https://developers.mercadolivre.com.br/
2. Crie uma aplicação (Meus Apps → Criar Aplicação)
3. Configure as credenciais no arquivo .env ou config.json
4. Execute: python scripts/mercadolivre_api.py --auth (para autorizar)
5. Execute: python scripts/mercadolivre_api.py --sync (para sincronizar produtos)

Documentação: https://developers.mercadolivre.com.br/pt_br/publicacao-de-produtos
"""

import json
import os
import sys
import re
import time
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode, parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

CONFIG_FILE = Path(__file__).parent.parent / 'config_mercadolivre.json'
PRODUCTS_FILE = Path(__file__).parent.parent / 'products.json'
LOG_FILE = Path(__file__).parent.parent / 'mercadolivre_sync.log'

# URLs da API
ML_API_URL = 'https://api.mercadolibre.com'
ML_AUTH_URL = 'https://auth.mercadolivre.com.br/authorization'
ML_TOKEN_URL = 'https://api.mercadolibre.com/oauth/token'

# Taxas do Mercado Livre por tipo de anúncio
ML_FEES = {
    'gold_special': 0.13,  # 13% - Clássico
    'gold_pro': 0.17,      # 17% - Premium
}

# Taxa fixa para vendas < R$ 79
ML_FIXED_FEE_THRESHOLD = 79.00
ML_FIXED_FEE = 6.00

# Custo médio de frete grátis (cobrado do vendedor pelo ML)
# Varia de R$ 15 a R$ 35 dependendo do peso/tamanho
ML_FRETE_MEDIO = 25.00

# Margem de segurança (para cobrir variações de frete e taxas)
SAFETY_MARGIN = 0.05  # 5% de margem

# Mapeamento de categorias (será preenchido dinamicamente)
CATEGORY_CACHE = {}


# =============================================================================
# CONFIGURAÇÃO E AUTENTICAÇÃO
# =============================================================================

def load_config():
    """Carrega configuração do arquivo."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(config):
    """Salva configuração no arquivo."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"✓ Configuração salva em {CONFIG_FILE}")


def setup_credentials():
    """Configura credenciais da API do Mercado Livre."""
    print("\n" + "="*60)
    print("CONFIGURAÇÃO DE CREDENCIAIS DO MERCADO LIVRE")
    print("="*60)
    print("""
Para obter suas credenciais:
1. Acesse https://developers.mercadolivre.com.br/
2. Faça login com sua conta do ML
3. Vá em 'Meus Apps' → 'Criar Aplicação'
4. Preencha:
   - Nome: Blumenau Automação Sync
   - Descrição: Sincronização de produtos
   - Redirect URI: http://localhost:8888/callback
5. Após criar, copie o App ID e Secret Key
    """)

    config = load_config()

    app_id = input("App ID (Client ID): ").strip()
    secret_key = input("Secret Key (Client Secret): ").strip()
    redirect_uri = input("Redirect URI [http://localhost:8888/callback]: ").strip()

    if not redirect_uri:
        redirect_uri = "http://localhost:8888/callback"

    config['app_id'] = app_id
    config['secret_key'] = secret_key
    config['redirect_uri'] = redirect_uri

    save_config(config)
    print("\n✓ Credenciais configuradas! Agora execute: --auth para autorizar")


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handler para receber o callback do OAuth."""

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if 'code' in query:
            self.server.auth_code = query['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: green;">&#10004; Autorizado com sucesso!</h1>
                <p>Pode fechar esta janela e voltar ao terminal.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error = query.get('error', ['unknown'])[0]
            self.wfile.write(f"<h1>Erro: {error}</h1>".encode())

    def log_message(self, format, *args):
        pass  # Silencia logs do servidor


def authorize():
    """Inicia fluxo de autorização OAuth."""
    config = load_config()

    if not config.get('app_id') or not config.get('secret_key'):
        print("❌ Credenciais não configuradas. Execute: --setup")
        return False

    # Monta URL de autorização
    params = {
        'response_type': 'code',
        'client_id': config['app_id'],
        'redirect_uri': config['redirect_uri'],
    }
    auth_url = f"{ML_AUTH_URL}?{urlencode(params)}"

    print("\n" + "="*60)
    print("AUTORIZAÇÃO DO MERCADO LIVRE")
    print("="*60)
    print(f"\nAbrindo navegador para autorização...")
    print(f"URL: {auth_url}\n")

    # Abre navegador
    webbrowser.open(auth_url)

    # Inicia servidor local para receber callback
    parsed = urlparse(config['redirect_uri'])
    port = parsed.port or 8888

    server = HTTPServer(('localhost', port), OAuthCallbackHandler)
    server.auth_code = None

    print(f"Aguardando autorização em http://localhost:{port}...")
    print("(Após autorizar no navegador, o processo continuará automaticamente)\n")

    while server.auth_code is None:
        server.handle_request()

    auth_code = server.auth_code
    print(f"✓ Código de autorização recebido!")

    # Troca código por tokens
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': config['app_id'],
        'client_secret': config['secret_key'],
        'code': auth_code,
        'redirect_uri': config['redirect_uri'],
    }

    response = requests.post(ML_TOKEN_URL, data=token_data)

    if response.status_code == 200:
        tokens = response.json()
        config['access_token'] = tokens['access_token']
        config['refresh_token'] = tokens['refresh_token']
        config['token_expires'] = time.time() + tokens['expires_in']
        config['user_id'] = tokens['user_id']
        save_config(config)

        print(f"\n✓ Autorização completa!")
        print(f"  User ID: {tokens['user_id']}")
        print(f"  Token válido por: {tokens['expires_in'] // 3600} horas")
        return True
    else:
        print(f"❌ Erro ao obter token: {response.text}")
        return False


def refresh_token():
    """Renova o access_token usando o refresh_token."""
    config = load_config()

    if not config.get('refresh_token'):
        print("❌ Refresh token não encontrado. Execute: --auth")
        return False

    token_data = {
        'grant_type': 'refresh_token',
        'client_id': config['app_id'],
        'client_secret': config['secret_key'],
        'refresh_token': config['refresh_token'],
    }

    response = requests.post(ML_TOKEN_URL, data=token_data)

    if response.status_code == 200:
        tokens = response.json()
        config['access_token'] = tokens['access_token']
        config['refresh_token'] = tokens['refresh_token']
        config['token_expires'] = time.time() + tokens['expires_in']
        save_config(config)
        print("✓ Token renovado com sucesso!")
        return True
    else:
        print(f"❌ Erro ao renovar token: {response.text}")
        return False


def get_access_token():
    """Obtém access_token válido, renovando se necessário."""
    config = load_config()

    if not config.get('access_token'):
        print("❌ Não autorizado. Execute: --auth")
        return None

    # Verifica se token expirou
    if config.get('token_expires', 0) < time.time():
        print("Token expirado, renovando...")
        if not refresh_token():
            return None
        config = load_config()

    return config['access_token']


# =============================================================================
# FUNÇÕES DA API
# =============================================================================

def api_get(endpoint, params=None):
    """Faz requisição GET na API."""
    token = get_access_token()
    if not token:
        return None

    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(f"{ML_API_URL}{endpoint}", headers=headers, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Erro API GET {endpoint}: {response.status_code} - {response.text}")
        return None


def api_post(endpoint, data):
    """Faz requisição POST na API."""
    token = get_access_token()
    if not token:
        return None

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    response = requests.post(f"{ML_API_URL}{endpoint}", headers=headers, json=data)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        print(f"❌ Erro API POST {endpoint}: {response.status_code} - {response.text}")
        return None


def api_put(endpoint, data):
    """Faz requisição PUT na API."""
    token = get_access_token()
    if not token:
        return None

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    response = requests.put(f"{ML_API_URL}{endpoint}", headers=headers, json=data)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Erro API PUT {endpoint}: {response.status_code} - {response.text}")
        return None


# =============================================================================
# CATEGORIAS
# =============================================================================

def search_category(query):
    """Busca categoria por termo."""
    response = requests.get(
        f"{ML_API_URL}/sites/MLB/domain_discovery/search",
        params={'q': query}
    )
    if response.status_code == 200:
        return response.json()
    return []


def get_category_info(category_id):
    """Obtém informações de uma categoria."""
    if category_id in CATEGORY_CACHE:
        return CATEGORY_CACHE[category_id]

    response = requests.get(f"{ML_API_URL}/categories/{category_id}")
    if response.status_code == 200:
        data = response.json()
        CATEGORY_CACHE[category_id] = data
        return data
    return None


def get_category_attributes(category_id):
    """Obtém atributos obrigatórios de uma categoria."""
    response = requests.get(f"{ML_API_URL}/categories/{category_id}/attributes")
    if response.status_code == 200:
        return response.json()
    return []


def is_category_valid(category_id):
    """Verifica se uma categoria existe e permite publicação."""
    cat_info = get_category_info(category_id)
    if not cat_info:
        return False
    settings = cat_info.get('settings', {})
    return settings.get('listing_allowed', False)


def find_best_category(product):
    """Encontra a melhor categoria ML para um produto."""
    title = product.get('name', '')

    # Busca por termos relevantes do produto
    search_terms = [
        title,
        product.get('category', ''),
        ' '.join(product.get('categoryPath', [])[:2] if product.get('categoryPath') else []),
        product.get('brand', ''),
    ]

    for term in search_terms:
        if not term:
            continue
        results = search_category(term)
        if results:
            for cat in results:
                cat_id = cat.get('category_id')
                if cat_id and is_category_valid(cat_id):
                    return cat_id

    # Fallback: tenta palavras do título progressivamente
    words = title.split()
    for i in range(min(4, len(words)), 0, -1):
        query = ' '.join(words[:i])
        results = search_category(query)
        if results:
            for cat in results:
                cat_id = cat.get('category_id')
                if cat_id and is_category_valid(cat_id):
                    return cat_id

    # Categoria padrão genérica
    return 'MLB1905'


# =============================================================================
# CÁLCULO DE PREÇOS
# =============================================================================

def calculate_ml_price(cost_price, listing_type='gold_special'):
    """
    Calcula preço ML para lucro zero, considerando:
    - Taxa de venda do ML (13% clássico)
    - Custo do frete grátis (cobrado do vendedor)
    - Margem de segurança (5%)

    Fórmula: preço = (custo + frete) / (1 - taxa - margem)
    """
    fee = ML_FEES.get(listing_type, 0.13)
    total_fee = fee + SAFETY_MARGIN  # 13% + 5% = 18%

    # Custo total = produto + frete médio
    total_cost = cost_price + ML_FRETE_MEDIO

    # Preço para cobrir custos após taxas
    ml_price = total_cost / (1 - total_fee)

    # Para produtos baratos, a taxa fixa pesa mais
    if ml_price < ML_FIXED_FEE_THRESHOLD:
        ml_price = (total_cost + ML_FIXED_FEE) / (1 - total_fee)

    # Garantir markup mínimo de 35% para segurança
    min_price = cost_price * 1.35
    if ml_price < min_price:
        ml_price = min_price

    return round(ml_price, 2)


# =============================================================================
# PREPARAÇÃO DE ANÚNCIOS
# =============================================================================

def clean_title(title, max_length=60):
    """Limpa título para ML."""
    title = ' '.join(title.split())
    title = re.sub(r'[|\\/<>]', ' ', title)
    title = ' '.join(title.split())

    if len(title) <= max_length:
        return title

    return title[:max_length-3].rsplit(' ', 1)[0] + '...'


def get_required_attributes(category_id):
    """Obtém atributos obrigatórios de uma categoria."""
    attrs = get_category_attributes(category_id)
    required = []
    for attr in attrs:
        tags = attr.get('tags', {})
        if tags.get('required') or tags.get('catalog_required'):
            required.append(attr)
    return required


def fill_required_attributes(category_id, product):
    """Preenche atributos obrigatórios da categoria com valores inferidos ou padrão."""
    required_attrs = get_required_attributes(category_id)
    attributes = []

    # Mapeamento de atributos para valores padrão
    default_values = {
        'POWER_SUPPLY_TYPE': 'Elétrica',
        'NETWORK_CABLE_TYPE': 'Ethernet',
        'CABLE_LENGTH': '5 m',
        'COLOR': 'Preto',
        'VOLTAGE': '220V',
        'MATERIAL': 'Plástico',
        'IS_RECHARGEABLE': 'Não',
        'INCLUDES_CHARGER': 'Não',
        'WITH_DISPLAY': 'Não',
        'IS_WIRELESS': 'Não',
        'CONNECTIVITY': 'Com fio',
        'PART_NUMBER': product.get('sku', product.get('id', '')),
        'ALPHANUMERIC_MODEL': product.get('sku', product.get('id', '')),
        'SELLER_SKU': product.get('sku', product.get('id', '')),
        'ITEM_CONDITION': 'Novo',
        'LINE': 'Industrial',
        'PACKAGE_WEIGHT': '500 g',
        'UNITS_PER_PACKAGE': '1',
        'SALE_FORMAT': 'Unidade',
        'MANUFACTURER': product.get('brand', 'Genérico'),
    }

    for attr in required_attrs:
        attr_id = attr.get('id')
        attr_name = attr.get('name', '')

        # Tenta encontrar valor nas specs do produto
        specs = product.get('specs', {})
        value = None

        # Busca no specs do produto
        for spec_key, spec_val in specs.items():
            if attr_name.lower() in spec_key.lower() or attr_id.lower() in spec_key.lower():
                value = spec_val
                break

        # Se não encontrou, usa valor padrão
        if not value and attr_id in default_values:
            value = default_values[attr_id]

        # Se ainda não encontrou, tenta usar o primeiro valor permitido
        if not value:
            allowed_values = attr.get('values', [])
            if allowed_values:
                value = allowed_values[0].get('name')

        # Adiciona o atributo se encontrou um valor
        if value:
            attr_entry = {'id': attr_id, 'value_name': str(value)}
            attributes.append(attr_entry)

    return attributes


def prepare_listing(product, listing_type='gold_special'):
    """Prepara dados do anúncio para a API."""
    cost_price = product.get('price', 0)
    if cost_price <= 0:
        return None

    ml_price = calculate_ml_price(cost_price, listing_type)
    category_id = find_best_category(product)

    # Monta descrição
    description = product.get('description', '')
    if not description:
        description = f"Produto: {product.get('name', 'Sem descrição')}"

    # Remove HTML
    description = re.sub(r'<[^>]+>', ' ', description)
    description = ' '.join(description.split())

    # Adiciona informações extras
    extras = []
    if product.get('brand'):
        extras.append(f"Marca: {product['brand']}")
    if product.get('warranty'):
        extras.append(f"Garantia: {product['warranty']}")
    if product.get('sku'):
        extras.append(f"Código: {product['sku']}")

    if extras:
        description += "\n\n" + "\n".join(extras)

    description += "\n\n---\nProduto novo, com nota fiscal.\nBlumenau Automação - Qualidade e confiança."

    # Prepara imagens
    pictures = []
    if product.get('image'):
        pictures.append({'source': product['image']})

    # Prepara atributos básicos
    attributes = []

    # Adiciona marca
    brand = product.get('brand', 'Genérico')
    attributes.append({
        'id': 'BRAND',
        'value_name': brand
    })

    # Adiciona modelo (usa SKU ou parte do nome)
    model = product.get('sku', '')
    if not model:
        # Extrai modelo do nome (primeira parte antes de | ou -)
        name = product.get('name', '')
        if '|' in name:
            model = name.split('|')[0].strip()[:60]
        elif '-' in name:
            model = name.split('-')[0].strip()[:60]
        else:
            model = name[:60]
    attributes.append({
        'id': 'MODEL',
        'value_name': model[:60]
    })

    # Adiciona GTIN/EAN se disponível
    gtin_val = product.get('ean') or product.get('gtin')
    if gtin_val:
        attributes.append({
            'id': 'GTIN',
            'value_name': str(gtin_val)
        })

    # Adiciona atributos obrigatórios da categoria
    required_attrs = fill_required_attributes(category_id, product)
    for attr in required_attrs:
        # Evita duplicatas
        if not any(a['id'] == attr['id'] for a in attributes):
            attributes.append(attr)

    # Monta payload
    listing = {
        'title': clean_title(product.get('name', '')),
        'category_id': category_id,
        'price': ml_price,
        'currency_id': 'BRL',
        'available_quantity': 10,  # Estoque padrão
        'buying_mode': 'buy_it_now',
        'listing_type_id': listing_type,
        'condition': 'new',
        'pictures': pictures,
        'attributes': attributes,
        'sale_terms': [
            {
                'id': 'WARRANTY_TYPE',
                'value_name': 'Garantia do vendedor'
            },
            {
                'id': 'WARRANTY_TIME',
                'value_name': '90 dias'
            }
        ],
        'tags': ['immediate_payment'],
        'seller_custom_field': product.get('sku', product.get('id', '')),
    }

    return {
        'listing': listing,
        'description': description[:50000],
        'product': product,
        'cost_price': cost_price,
        'ml_price': ml_price,
        'category_id': category_id,
    }


# =============================================================================
# SINCRONIZAÇÃO
# =============================================================================

def get_my_items():
    """Lista todos os itens do vendedor."""
    config = load_config()
    user_id = config.get('user_id')

    if not user_id:
        print("❌ User ID não encontrado. Execute: --auth")
        return []

    items = []
    offset = 0
    limit = 50

    while True:
        result = api_get(f"/users/{user_id}/items/search", {
            'offset': offset,
            'limit': limit,
        })

        if not result:
            break

        items.extend(result.get('results', []))

        if len(result.get('results', [])) < limit:
            break

        offset += limit

    return items


def create_listing(prepared):
    """Cria um anúncio no ML, com retry usando categoria genérica se falhar."""
    listing = prepared['listing']
    description = prepared['description']

    # Cria o item
    result = api_post('/items', listing)

    # Se falhou, tenta com categoria genérica MLB1905 (modo classified)
    if not result and listing.get('category_id') != 'MLB1905':
        original_cat = listing['category_id']
        listing['category_id'] = 'MLB1905'
        listing['buying_mode'] = 'classified'
        listing['listing_type_id'] = 'silver'
        listing.pop('tags', None)
        listing.pop('sale_terms', None)
        # Remove atributos específicos da categoria anterior
        listing['attributes'] = [
            a for a in listing.get('attributes', [])
            if a['id'] in ('BRAND', 'MODEL', 'ITEM_CONDITION', 'SELLER_SKU')
        ]
        print(f"  ↳ Retry com MLB1905/classified (era {original_cat})...")
        result = api_post('/items', listing)

    if not result:
        return None

    item_id = result.get('id')

    # Adiciona descrição
    if item_id and description:
        api_post(f'/items/{item_id}/description', {
            'plain_text': description
        })

    return result


def sync_products(dry_run=False, limit=None):
    """Sincroniza produtos com o Mercado Livre."""
    print("\n" + "="*60)
    print("SINCRONIZAÇÃO DE PRODUTOS - MERCADO LIVRE")
    print("="*60)

    # Carrega produtos
    with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    products = data.get('products', [])

    # Filtra produtos válidos
    valid_products = [
        p for p in products
        if p.get('inStock', False) and p.get('price', 0) > 0
    ]

    if limit:
        valid_products = valid_products[:limit]

    print(f"\nProdutos a sincronizar: {len(valid_products)}")

    if dry_run:
        print("\n⚠️  MODO SIMULAÇÃO (dry-run) - Nenhum anúncio será criado\n")

    # Obtém itens existentes via ml_products_map.json (muito mais rápido que consultar API)
    ml_map_file = Path(__file__).parent.parent / 'ml_products_map.json'
    existing_skus = set()
    if ml_map_file.exists():
        with open(ml_map_file, 'r') as f:
            ml_map = json.load(f)
        existing_skus = set(ml_map.keys())
    else:
        ml_map = {}

    print(f"Anúncios existentes (via mapa): {len(existing_skus)}")

    # Estatísticas
    stats = {
        'total': len(valid_products),
        'created': 0,
        'skipped': 0,
        'errors': 0,
        'total_cost': 0,
        'total_ml_price': 0,
    }

    # Log
    log_entries = []

    for i, product in enumerate(valid_products, 1):
        sku = product.get('sku', product.get('id', ''))

        print(f"\n[{i}/{len(valid_products)}] {product.get('name', 'Sem nome')[:50]}...")

        # Verifica se já existe
        if sku in existing_skus:
            print(f"  → Já existe (SKU: {sku}), pulando...")
            stats['skipped'] += 1
            continue

        # Prepara anúncio
        prepared = prepare_listing(product)

        if not prepared:
            print(f"  → Erro ao preparar anúncio")
            stats['errors'] += 1
            continue

        stats['total_cost'] += prepared['cost_price']
        stats['total_ml_price'] += prepared['ml_price']

        print(f"  Custo: R$ {prepared['cost_price']:.2f} → ML: R$ {prepared['ml_price']:.2f}")

        if dry_run:
            print(f"  [SIMULAÇÃO] Anúncio seria criado")
            stats['created'] += 1
            continue

        # Cria anúncio
        result = create_listing(prepared)

        if result:
            ml_id = result.get('id', '')
            print(f"  ✓ Criado: {ml_id} - {result.get('permalink', '')}")
            stats['created'] += 1
            log_entries.append({
                'timestamp': datetime.now().isoformat(),
                'action': 'created',
                'item_id': ml_id,
                'sku': sku,
                'title': prepared['listing']['title'],
                'price': prepared['ml_price'],
            })
            # Atualiza mapa local
            ml_map[sku] = {
                'ml_id': ml_id,
                'status': 'active',
                'price': prepared['ml_price'],
            }
            # Salva mapa a cada 10 criações
            if stats['created'] % 10 == 0:
                with open(ml_map_file, 'w') as f:
                    json.dump(ml_map, f, indent=2, ensure_ascii=False)
        else:
            print(f"  ✗ Erro ao criar anúncio")
            stats['errors'] += 1

        # Rate limiting
        time.sleep(1)

    # Salva mapa ML atualizado
    if ml_map:
        with open(ml_map_file, 'w') as f:
            json.dump(ml_map, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Mapa ML salvo: {len(ml_map)} produtos")

    # Salva log
    if log_entries:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            for entry in log_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    # Relatório final
    print("\n" + "="*60)
    print("RELATÓRIO FINAL")
    print("="*60)
    print(f"\nTotal processado: {stats['total']}")
    print(f"Criados: {stats['created']}")
    print(f"Já existentes: {stats['skipped']}")
    print(f"Erros: {stats['errors']}")
    print(f"\nValores:")
    print(f"  Custo total: R$ {stats['total_cost']:,.2f}")
    print(f"  Preço ML total: R$ {stats['total_ml_price']:,.2f}")
    if stats['total_cost'] > 0:
        markup = ((stats['total_ml_price'] / stats['total_cost']) - 1) * 100
        print(f"  Markup médio: {markup:.1f}%")

    return stats


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Integração Blumenau Automação com Mercado Livre',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python mercadolivre_api.py --setup     # Configura credenciais
  python mercadolivre_api.py --auth      # Autoriza aplicação
  python mercadolivre_api.py --sync      # Sincroniza todos os produtos
  python mercadolivre_api.py --sync --limit 10   # Sincroniza 10 produtos
  python mercadolivre_api.py --sync --dry-run    # Simula sem criar
  python mercadolivre_api.py --list      # Lista anúncios existentes
        """
    )

    parser.add_argument('--setup', action='store_true',
                        help='Configura credenciais da API')
    parser.add_argument('--auth', action='store_true',
                        help='Autoriza aplicação no Mercado Livre')
    parser.add_argument('--refresh', action='store_true',
                        help='Renova token de acesso')
    parser.add_argument('--sync', action='store_true',
                        help='Sincroniza produtos')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simula sincronização sem criar anúncios')
    parser.add_argument('--limit', type=int,
                        help='Limita quantidade de produtos a sincronizar')
    parser.add_argument('--list', action='store_true',
                        help='Lista anúncios existentes')
    parser.add_argument('--search-cat', type=str,
                        help='Busca categoria por termo')

    args = parser.parse_args()

    if args.setup:
        setup_credentials()
    elif args.auth:
        authorize()
    elif args.refresh:
        refresh_token()
    elif args.sync:
        sync_products(dry_run=args.dry_run, limit=args.limit)
    elif args.list:
        items = get_my_items()
        print(f"\nTotal de anúncios: {len(items)}")
        for item_id in items[:20]:
            item = api_get(f'/items/{item_id}')
            if item:
                print(f"  {item_id}: {item.get('title', 'N/A')[:50]} - R$ {item.get('price', 0):.2f}")
        if len(items) > 20:
            print(f"  ... e mais {len(items) - 20} anúncios")
    elif args.search_cat:
        results = search_category(args.search_cat)
        print(f"\nCategorias encontradas para '{args.search_cat}':")
        for cat in results[:10]:
            print(f"  {cat.get('category_id')}: {cat.get('category_name')}")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
