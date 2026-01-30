#!/usr/bin/env python3
"""
Scraper de produtos para Blumenau Automação
Importa produtos da Proesi (e futuramente LojaVale)
"""

import json
import re
import time
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Diretório base do projeto
BASE_DIR = Path(__file__).parent.parent
PRODUCTS_FILE = BASE_DIR / "products.json"

# Headers para requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
}


class BaseScraper(ABC):
    """Classe base para scrapers de fornecedores"""

    def __init__(self, min_price: float = 100.0, delay: float = 1.5):
        self.min_price = min_price
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Nome do fornecedor"""
        pass

    @abstractmethod
    def get_product_urls(self) -> list[str]:
        """Retorna lista de URLs de produtos"""
        pass

    @abstractmethod
    def parse_product(self, url: str) -> Optional[dict]:
        """Faz parse de uma página de produto"""
        pass

    def fetch(self, url: str, retries: int = 3) -> Optional[str]:
        """Faz fetch de uma URL com retry"""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                logger.warning(f"Tentativa {attempt + 1}/{retries} falhou para {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        return None

    def scrape_all(self, limit: Optional[int] = None, save_callback=None, save_interval: int = 50) -> list[dict]:
        """Scrape todos os produtos com salvamento incremental"""
        urls = self.get_product_urls()
        logger.info(f"Encontradas {len(urls)} URLs de produtos")

        if limit:
            urls = urls[:limit]
            logger.info(f"Limitando a {limit} produtos (modo teste)")

        products = []
        last_save_count = 0

        for i, url in enumerate(urls):
            logger.info(f"Processando {i + 1}/{len(urls)}: {url}")

            product = self.parse_product(url)
            if product:
                # Filtrar por preço mínimo
                if product.get('price') and product['price'] >= self.min_price:
                    products.append(product)
                    logger.info(f"  ✓ {product['name']} - R$ {product['price']:.2f}")

                    # Salvar incrementalmente
                    if save_callback and len(products) >= last_save_count + save_interval:
                        save_callback(products, self.source_name)
                        last_save_count = len(products)
                        logger.info(f"  📁 Salvamento incremental: {len(products)} produtos")

                elif product.get('price'):
                    logger.info(f"  ✗ Preço abaixo do mínimo: R$ {product['price']:.2f}")
                else:
                    logger.info(f"  ✗ Preço não encontrado")
            else:
                logger.warning(f"  ✗ Falha ao processar produto")

            # Rate limiting
            time.sleep(self.delay)

        return products


class ProesiScraper(BaseScraper):
    """Scraper para www.proesi.com.br"""

    SITEMAP_URL = "https://www.proesi.com.br/sitemap-produto.xml"
    BASE_URL = "https://www.proesi.com.br"

    @property
    def source_name(self) -> str:
        return "proesi"

    def get_product_urls(self) -> list[str]:
        """Baixa sitemap e extrai URLs de produtos"""
        logger.info(f"Baixando sitemap: {self.SITEMAP_URL}")

        xml = self.fetch(self.SITEMAP_URL)
        if not xml:
            logger.error("Falha ao baixar sitemap")
            return []

        soup = BeautifulSoup(xml, 'lxml-xml')
        all_urls = [loc.text for loc in soup.find_all('loc')]

        # Filtrar apenas URLs de produtos (excluir CDN, imagens, etc)
        urls = [
            url for url in all_urls
            if url.startswith('https://www.proesi.com.br/')
            and not url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
            and 'cdn.magazord' not in url
        ]

        logger.info(f"Extraídas {len(urls)} URLs de produtos (de {len(all_urls)} no sitemap)")
        return urls

    def parse_product(self, url: str) -> Optional[dict]:
        """Parse de página de produto da Proesi"""
        html = self.fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, 'html.parser')

        try:
            # Nome do produto
            name_el = soup.select_one('h1.product-name, h1[itemprop="name"], .product-title h1')
            name = name_el.get_text(strip=True) if name_el else None

            if not name:
                # Tentar pegar do title da página
                title = soup.find('title')
                if title:
                    name = title.get_text(strip=True).split('|')[0].strip()

            if not name:
                return None

            # SKU
            sku = None

            # 1. Proesi: SKU na seção de características (Referência)
            ref_el = soup.select_one('.caract-referencia dd, .product-sku dd')
            if ref_el:
                sku = ref_el.get_text(strip=True)

            # 2. Itemprop sku ou classes comuns
            if not sku:
                sku_el = soup.select_one('[itemprop="sku"], .product-sku, .sku-value')
                if sku_el:
                    sku_text = sku_el.get_text(strip=True)
                    # Remover prefixos como "Modelo:", "SKU:", "Ref:"
                    sku = re.sub(r'^(modelo|sku|ref|referência|código):\s*', '', sku_text, flags=re.IGNORECASE)

            # 3. Tentar extrair do script de analytics
            if not sku:
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string and 'item_id' in script.string:
                        match = re.search(r'"item_id"\s*:\s*"([^"]+)"', script.string)
                        if match:
                            sku = match.group(1)
                            break
                            break

            # Preço
            price = None
            price_el = soup.select_one('.price-value, .product-price, [itemprop="price"], .primary-price .valor-big')
            if price_el:
                price_text = price_el.get_text(strip=True)
                # Extrair valor numérico (ex: "R$ 123,45" -> 123.45)
                price_match = re.search(r'[\d.,]+', price_text.replace('.', '').replace(',', '.'))
                if price_match:
                    try:
                        price = float(price_match.group())
                    except ValueError:
                        pass

            # Também tentar meta tag
            if not price:
                price_meta = soup.select_one('meta[itemprop="price"], meta[property="product:price:amount"]')
                if price_meta and price_meta.get('content'):
                    try:
                        price = float(price_meta['content'].replace(',', '.'))
                    except ValueError:
                        pass

            # Estoque
            stock = None
            in_stock = True
            stock_el = soup.select_one('.stock-quantity, .availability, [itemprop="availability"]')
            if stock_el:
                stock_text = stock_el.get_text(strip=True).lower()
                if 'indisponível' in stock_text or 'esgotado' in stock_text:
                    in_stock = False
                    stock = 0
                else:
                    stock_match = re.search(r'(\d+)', stock_text)
                    if stock_match:
                        stock = int(stock_match.group(1))

            # Marca
            brand = None
            brand_el = soup.select_one('[itemprop="brand"], .product-brand, .marca')
            if brand_el:
                brand = brand_el.get_text(strip=True)

            # Imagens (principal + galeria)
            image = None
            images = []

            # Pegar todas as imagens do produto
            img_elements = soup.select('[itemprop="image"], .product-image img, .gallery-image img')
            for img_el in img_elements:
                img_url = img_el.get('data-src-max') or img_el.get('data-img-full') or img_el.get('data-src') or img_el.get('src')
                if img_url and img_url.startswith('http') and 'svg' not in img_url and img_url not in images:
                    # Remover parâmetros de redimensionamento para pegar imagem original
                    if '?ims=' in img_url:
                        img_url = img_url.split('?ims=')[0]
                    images.append(img_url)

            if images:
                image = images[0]  # Imagem principal
            elif img_elements:
                # Fallback
                img_el = img_elements[0]
                image = img_el.get('src') or img_el.get('data-src')
                if image and not image.startswith('http'):
                    image = urljoin(self.BASE_URL, image)

            # Descrição - tentar múltiplas fontes (Proesi específico)
            description = None

            # 1. Aba de descrição do produto (Proesi)
            desc_el = soup.select_one('#descricao-produto .content, .descricao-produto .content')
            if desc_el:
                # Pegar texto completo, preservando parágrafos
                paragraphs = desc_el.find_all(['p', 'h2', 'h3', 'li'])
                if paragraphs:
                    description = ' '.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
                else:
                    description = desc_el.get_text(strip=True)

            # 2. Meta description como fallback
            if not description:
                meta_desc = soup.select_one('meta[name="description"]')
                if meta_desc and meta_desc.get('content'):
                    description = meta_desc['content'].strip()

            # 3. Outros seletores comuns
            if not description:
                desc_el = soup.select_one('.product-description, [itemprop="description"], .description-content')
                if desc_el:
                    description = desc_el.get_text(strip=True)

            # 4. Tentar pegar do JSON-LD
            if not description:
                for script in soup.find_all('script', type='application/ld+json'):
                    try:
                        import json
                        data = json.loads(script.string)
                        if isinstance(data, dict) and data.get('description'):
                            description = data['description']
                            break
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and item.get('description'):
                                    description = item['description']
                                    break
                    except:
                        pass

            # Decodificar entidades HTML e limitar tamanho
            if description:
                import html
                description = html.unescape(description)
                if len(description) > 2000:
                    description = description[:1997] + '...'

            # Categoria
            category = None
            category_path = []
            breadcrumb = soup.select('.breadcrumb a, .breadcrumbs a, nav[aria-label="breadcrumb"] a')
            if breadcrumb:
                category_path = [a.get_text(strip=True) for a in breadcrumb[1:]]  # Skip "Home"
                if category_path:
                    category = category_path[-1].lower().replace(' ', '-')

            # Especificações técnicas / Características (Proesi específico)
            specs = {}

            # 1. Características Proesi (dl > dt/dd)
            carac_section = soup.select_one('#caracteristicas .caracteristicas-lista-corrida, .caracteristicas-produto')
            if carac_section:
                # Pegar pares dt/dd
                dts = carac_section.select('dt')
                dds = carac_section.select('dd')
                for dt, dd in zip(dts, dds):
                    key = dt.get_text(strip=True)
                    value = dd.get_text(strip=True)
                    if key and value and key.lower() != 'referência':  # Pular referência (já temos SKU)
                        specs[key] = value

            # 2. Tabelas de especificações genéricas
            if not specs:
                spec_table = soup.select('.product-specs tr, .specifications tr, .technical-data tr')
                for row in spec_table:
                    cells = row.find_all(['th', 'td'])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        if key and value:
                            specs[key] = value

            # Datasheet
            datasheet = None
            datasheet_el = soup.select_one('a[href*="datasheet"], a[href*="manual"], a[href$=".pdf"]')
            if datasheet_el:
                datasheet = datasheet_el.get('href')
                if datasheet and not datasheet.startswith('http'):
                    datasheet = urljoin(self.BASE_URL, datasheet)

            # Slug (extrair da URL)
            slug = url.replace(self.BASE_URL, '').strip('/')

            return {
                'id': sku or slug,
                'sku': sku,
                'name': name,
                'slug': slug,
                'brand': brand,
                'price': price,
                'priceFormatted': f"R$ {price:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if price else None,
                'stock': stock,
                'inStock': in_stock,
                'description': description,
                'specs': specs if specs else None,
                'category': category,
                'categoryPath': category_path if category_path else None,
                'image': image,
                'images': images if len(images) > 1 else None,  # Galeria de imagens
                'datasheet': datasheet,
                'sourceUrl': url
            }

        except Exception as e:
            logger.error(f"Erro ao processar {url}: {e}")
            return None


class LojaValeScraper(BaseScraper):
    """Scraper para www.lojavale.com.br (para implementação futura)"""

    @property
    def source_name(self) -> str:
        return "lojavale"

    def get_product_urls(self) -> list[str]:
        # TODO: Implementar quando necessário
        raise NotImplementedError("LojaVale scraper ainda não implementado")

    def parse_product(self, url: str) -> Optional[dict]:
        raise NotImplementedError("LojaVale scraper ainda não implementado")


def generate_categories(products: list[dict]) -> list[dict]:
    """Gera lista de categorias a partir dos produtos"""
    category_counts = {}

    for product in products:
        if product.get('category'):
            cat = product['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1

    categories = [
        {'id': cat_id, 'name': cat_id.replace('-', ' ').title(), 'count': count}
        for cat_id, count in sorted(category_counts.items(), key=lambda x: -x[1])
    ]

    return categories


def save_products(products: list[dict], source: str):
    """Salva produtos no arquivo JSON"""
    # Carregar produtos existentes para comparar
    old_products = {}
    if PRODUCTS_FILE.exists():
        try:
            with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                old_products = {p['id']: p for p in old_data.get('products', [])}
        except json.JSONDecodeError:
            pass

    # Gerar relatório de mudanças
    new_products = {p['id']: p for p in products}

    added = set(new_products.keys()) - set(old_products.keys())
    removed = set(old_products.keys()) - set(new_products.keys())

    price_changed = []
    for pid in set(new_products.keys()) & set(old_products.keys()):
        old_price = old_products[pid].get('price')
        new_price = new_products[pid].get('price')
        if old_price != new_price:
            price_changed.append({
                'id': pid,
                'name': new_products[pid]['name'],
                'old_price': old_price,
                'new_price': new_price
            })

    # Log mudanças
    if added:
        logger.info(f"Novos produtos: {len(added)}")
    if removed:
        logger.info(f"Produtos removidos: {len(removed)}")
    if price_changed:
        logger.info(f"Preços alterados: {len(price_changed)}")
        for change in price_changed[:5]:  # Mostrar só os 5 primeiros
            logger.info(f"  {change['name']}: R$ {change['old_price']} -> R$ {change['new_price']}")

    # Gerar categorias
    categories = generate_categories(products)

    # Montar dados finais
    data = {
        'lastUpdated': datetime.now(timezone.utc).isoformat(),
        'source': source,
        'totalProducts': len(products),
        'products': products,
        'categories': categories
    }

    # Salvar
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Salvos {len(products)} produtos em {PRODUCTS_FILE}")

    return {
        'added': len(added),
        'removed': len(removed),
        'price_changed': len(price_changed),
        'total': len(products)
    }


def main():
    parser = argparse.ArgumentParser(description='Scraper de produtos')
    parser.add_argument('--test', action='store_true', help='Modo teste (processa só 10 produtos)')
    parser.add_argument('--source', choices=['proesi', 'lojavale'], default='proesi', help='Fonte de produtos')
    parser.add_argument('--min-price', type=float, default=100.0, help='Preço mínimo (default: 100)')
    parser.add_argument('--delay', type=float, default=1.5, help='Delay entre requests em segundos')
    args = parser.parse_args()

    logger.info(f"Iniciando scraper - Fonte: {args.source}, Preço mínimo: R$ {args.min_price}")

    # Selecionar scraper
    if args.source == 'proesi':
        scraper = ProesiScraper(min_price=args.min_price, delay=args.delay)
    elif args.source == 'lojavale':
        scraper = LojaValeScraper(min_price=args.min_price, delay=args.delay)
    else:
        logger.error(f"Fonte desconhecida: {args.source}")
        return 1

    # Executar scraping com salvamento incremental
    limit = 10 if args.test else None
    # Salvar a cada 10 produtos (produtos caros são raros)
    save_interval = 10
    products = scraper.scrape_all(
        limit=limit,
        save_callback=save_products,
        save_interval=save_interval
    )

    if not products:
        logger.warning("Nenhum produto encontrado!")
        return 1

    # Salvar resultados
    stats = save_products(products, scraper.source_name)

    logger.info(f"Concluído! Total: {stats['total']}, Novos: {stats['added']}, Removidos: {stats['removed']}, Preços alterados: {stats['price_changed']}")

    return 0


if __name__ == '__main__':
    exit(main())
