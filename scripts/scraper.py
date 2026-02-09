#!/usr/bin/env python3
"""
Scraper de produtos para Blumenau Automação
Importa produtos de Proesi, Loja Vale e Seel Distribuidora (todos usam Magazord)
Suporta:
- Processamento paralelo (multi-threaded)
- Continuar de onde parou (resume)
- Updates incrementais (só processa produtos que mudaram)
- Exportação para Mercado Livre/Shopee
"""

import json
import re
import time
import argparse
import logging
import sqlite3
import hashlib
import html
import csv
from datetime import datetime, timezone
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

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
DB_FILE = BASE_DIR / "scripts" / "products.db"

# Headers para requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
}

# Configuração dos fornecedores
SUPPLIERS = {
    'proesi': {
        'name': 'Proesi',
        'base_url': 'https://www.proesi.com.br',
        'sitemap': 'https://www.proesi.com.br/sitemap-produto.xml',
        'id_prefix': '',
    },
    'lojavale': {
        'name': 'Loja Vale',
        'base_url': 'https://www.lojavale.com.br',
        'sitemap': 'https://www.lojavale.com.br/sitemap-produto.xml',
        'id_prefix': 'LV-',
    },
    'seel': {
        'name': 'Seel Distribuidora',
        'base_url': 'https://www.seeldistribuidora.com.br',
        'sitemap': 'https://www.seeldistribuidora.com.br/sitemap-produto.xml',
        'id_prefix': 'SE-',
    },
}


@dataclass
class Product:
    """Estrutura de dados do produto"""
    id: str
    sku: str
    name: str
    slug: str
    price: float
    priceFormatted: str
    sourceUrl: str
    supplier: str
    inStock: bool = True
    brand: Optional[str] = None
    pricePix: Optional[float] = None
    stock: Optional[int] = None
    description: Optional[str] = None
    specs: Optional[Dict[str, str]] = None
    category: Optional[str] = None
    categoryPath: Optional[List[str]] = None
    image: Optional[str] = None
    images: Optional[List[str]] = None
    videos: Optional[List[Dict[str, str]]] = None  # Lista de vídeos: {url, platform}
    datasheet: Optional[str] = None
    warranty: Optional[str] = None
    # Campos para marketplace
    gtin: Optional[str] = None
    weight_kg: Optional[float] = None
    dimensions_cm: Optional[Dict[str, float]] = None

    def to_dict(self) -> dict:
        """Converte para dicionário, removendo None"""
        d = asdict(self)
        # Remover campos None para JSON mais limpo
        return {k: v for k, v in d.items() if v is not None}

    def content_hash(self) -> str:
        """Gera hash do conteúdo para detectar mudanças"""
        content = f"{self.name}|{self.price}|{self.inStock}|{self.description or ''}"
        return hashlib.md5(content.encode()).hexdigest()


class ProductsDB:
    """Banco SQLite para tracking de produtos e progresso"""

    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Cria tabelas se não existirem"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products_cache (
                    id TEXT PRIMARY KEY,
                    supplier TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    price REAL,
                    content_hash TEXT,
                    last_scraped TEXT,
                    source_url TEXT,
                    UNIQUE(supplier, sku)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS urls_progress (
                    url TEXT PRIMARY KEY,
                    supplier TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    processed_at TEXT,
                    result TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    products_found INTEGER,
                    products_new INTEGER,
                    products_updated INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_urls_supplier ON urls_progress(supplier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_urls_status ON urls_progress(status)")
            conn.commit()

    def get_cached_product(self, supplier: str, sku: str) -> Optional[dict]:
        """Retorna produto em cache se existir"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM products_cache WHERE supplier = ? AND sku = ?",
                    (supplier, sku)
                ).fetchone()
                return dict(row) if row else None

    def update_product_cache(self, product: Product):
        """Atualiza cache do produto"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO products_cache
                    (id, supplier, sku, price, content_hash, last_scraped, source_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    product.id,
                    product.supplier,
                    product.sku,
                    product.price,
                    product.content_hash(),
                    datetime.now(timezone.utc).isoformat(),
                    product.sourceUrl
                ))
                conn.commit()

    def product_changed(self, product: Product) -> bool:
        """Verifica se produto mudou desde última execução"""
        cached = self.get_cached_product(product.supplier, product.sku)
        if not cached:
            return True  # Produto novo
        return cached.get('content_hash') != product.content_hash()

    def register_urls(self, urls: List[str], supplier: str):
        """Registra URLs para processar"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                for url in urls:
                    conn.execute("""
                        INSERT OR IGNORE INTO urls_progress (url, supplier, status)
                        VALUES (?, ?, 'pending')
                    """, (url, supplier))
                conn.commit()

    def get_pending_urls(self, supplier: str) -> List[str]:
        """Retorna URLs pendentes de processamento"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT url FROM urls_progress WHERE supplier = ? AND status = 'pending'",
                    (supplier,)
                ).fetchall()
                return [r[0] for r in rows]

    def get_all_urls(self, supplier: str) -> List[str]:
        """Retorna todas as URLs registradas para o fornecedor"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT url FROM urls_progress WHERE supplier = ?",
                    (supplier,)
                ).fetchall()
                return [r[0] for r in rows]

    def mark_url_done(self, url: str, result: str = 'ok'):
        """Marca URL como processada"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE urls_progress SET status = 'done', processed_at = ?, result = ?
                    WHERE url = ?
                """, (datetime.now(timezone.utc).isoformat(), result, url))
                conn.commit()

    def mark_url_error(self, url: str, error: str):
        """Marca URL com erro"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE urls_progress SET status = 'error', processed_at = ?, result = ?
                    WHERE url = ?
                """, (datetime.now(timezone.utc).isoformat(), error[:500], url))
                conn.commit()

    def reset_urls(self, supplier: str):
        """Reseta progresso de URLs para um fornecedor"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM urls_progress WHERE supplier = ?", (supplier,))
                conn.commit()

    def get_progress(self, supplier: str) -> dict:
        """Retorna estatísticas de progresso"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM urls_progress WHERE supplier = ?", (supplier,)
                ).fetchone()[0]
                done = conn.execute(
                    "SELECT COUNT(*) FROM urls_progress WHERE supplier = ? AND status = 'done'", (supplier,)
                ).fetchone()[0]
                errors = conn.execute(
                    "SELECT COUNT(*) FROM urls_progress WHERE supplier = ? AND status = 'error'", (supplier,)
                ).fetchone()[0]
                return {'total': total, 'done': done, 'errors': errors, 'pending': total - done - errors}

    def log_run(self, supplier: str, found: int, new: int, updated: int):
        """Registra execução do scraper"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO scrape_runs
                    (supplier, started_at, finished_at, products_found, products_new, products_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    supplier,
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    found, new, updated
                ))
                conn.commit()


class BaseScraper(ABC):
    """Classe base para scrapers de fornecedores"""

    def __init__(self, min_price: float = 100.0, delay: float = 0.5, workers: int = 5):
        self.min_price = min_price
        self.delay = delay
        self.workers = workers
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        """Retorna sessão thread-local"""
        if not hasattr(self._local, 'session'):
            self._local.session = requests.Session()
            self._local.session.headers.update(HEADERS)
        return self._local.session

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
    def parse_product(self, url: str) -> Optional[Product]:
        """Faz parse de uma página de produto"""
        pass

    def fetch(self, url: str, retries: int = 3) -> Optional[str]:
        """Faz fetch de uma URL com retry"""
        session = self._get_session()
        for attempt in range(retries):
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        return None

    def _process_url(self, url: str, db: Optional[ProductsDB], incremental: bool) -> Optional[Product]:
        """Processa uma única URL (para uso em thread)"""
        try:
            product = self.parse_product(url)
            if product:
                # Filtrar por preço mínimo
                if product.price and product.price >= self.min_price:
                    # Verificar se mudou (modo incremental)
                    if incremental and db and not db.product_changed(product):
                        if db:
                            db.mark_url_done(url, 'unchanged')
                        return None

                    # Atualizar cache
                    if db:
                        db.update_product_cache(product)
                        db.mark_url_done(url, 'ok')

                    return product
                else:
                    if db:
                        db.mark_url_done(url, f'price_below_{self.min_price}')
            else:
                if db:
                    db.mark_url_done(url, 'no_data')

        except Exception as e:
            if db:
                db.mark_url_error(url, str(e))
            logger.error(f"Erro processando {url}: {e}")

        return None

    def scrape_all(self, limit: Optional[int] = None, save_callback=None,
                   save_interval: int = 50, db: Optional[ProductsDB] = None,
                   incremental: bool = False, resume: bool = False) -> list[Product]:
        """Scrape todos os produtos com processamento paralelo"""

        # Obter URLs
        if resume and db:
            # Tentar continuar de onde parou
            pending_urls = db.get_pending_urls(self.source_name)
            if pending_urls:
                logger.info(f"Continuando de onde parou: {len(pending_urls)} URLs pendentes")
                urls = pending_urls
            else:
                # Verificar se já tem URLs registradas
                all_urls = db.get_all_urls(self.source_name)
                if all_urls:
                    logger.info(f"Todas as {len(all_urls)} URLs já foram processadas")
                    return []
                # Buscar novas URLs
                urls = self.get_product_urls()
                db.register_urls(urls, self.source_name)
        else:
            urls = self.get_product_urls()
            if db:
                # Resetar e registrar novas URLs
                db.reset_urls(self.source_name)
                db.register_urls(urls, self.source_name)

        logger.info(f"Encontradas {len(urls)} URLs de produtos")

        if limit:
            urls = urls[:limit]
            logger.info(f"Limitando a {limit} produtos (modo teste)")

        products = []
        products_lock = threading.Lock()
        processed = 0
        processed_lock = threading.Lock()

        def process_and_collect(url: str) -> None:
            nonlocal processed
            product = self._process_url(url, db, incremental)

            with processed_lock:
                processed += 1
                current = processed

            if product:
                with products_lock:
                    products.append(product)
                    count = len(products)

                logger.info(f"[{current}/{len(urls)}] ✓ {product.name[:50]}... - R$ {product.price:.2f}")

                # Salvar incrementalmente
                if save_callback and count % save_interval == 0:
                    with products_lock:
                        save_callback(list(products), self.source_name)
                    logger.info(f"  📁 Salvamento incremental: {count} produtos")
            else:
                if current % 100 == 0:
                    logger.info(f"[{current}/{len(urls)}] Progresso...")

            # Rate limiting por thread
            time.sleep(self.delay)

        # Processar em paralelo
        logger.info(f"Iniciando processamento paralelo com {self.workers} workers...")
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {executor.submit(process_and_collect, url): url for url in urls}

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    url = futures[future]
                    logger.error(f"Erro em thread para {url}: {e}")

        logger.info(f"Processamento concluído: {len(products)} produtos válidos de {len(urls)} URLs")
        return products


class MagazordScraper(BaseScraper):
    """Scraper unificado para sites Magazord (Proesi, Loja Vale, Seel)"""

    def __init__(self, supplier_key: str, min_price: float = 100.0, delay: float = 0.5, workers: int = 5):
        super().__init__(min_price, delay, workers)
        if supplier_key not in SUPPLIERS:
            raise ValueError(f"Fornecedor desconhecido: {supplier_key}")
        self.supplier_key = supplier_key
        self.config = SUPPLIERS[supplier_key]

    @property
    def source_name(self) -> str:
        return self.config['name']

    @property
    def base_url(self) -> str:
        return self.config['base_url']

    @property
    def id_prefix(self) -> str:
        return self.config['id_prefix']

    def get_product_urls(self) -> list[str]:
        """Baixa sitemap e extrai URLs de produtos"""
        sitemap_url = self.config['sitemap']
        logger.info(f"Baixando sitemap: {sitemap_url}")

        xml = self.fetch(sitemap_url)
        if not xml:
            logger.error("Falha ao baixar sitemap")
            return []

        soup = BeautifulSoup(xml, 'lxml-xml')
        all_urls = [loc.text for loc in soup.find_all('loc')]

        # Filtrar apenas URLs de produtos (excluir CDN, imagens, etc)
        urls = [
            url for url in all_urls
            if url.startswith(self.base_url)
            and not url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf'))
            and 'cdn.magazord' not in url
        ]

        logger.info(f"Extraídas {len(urls)} URLs de produtos (de {len(all_urls)} no sitemap)")
        return urls

    def _extract_data_product(self, html_content: str) -> Optional[dict]:
        """Extrai objeto dataProduct do JavaScript.

        Magazord sites use different formats:
        - Loja Vale: `const dataProduct = { id: '...', produto: {...}, ... };`
          The outer object has JS keys (unquoted), but the inner `produto` value
          is a valid JSON object with "produto_id", "midias", etc.
        - Some sites: `window.dataProduct = {...};`
        - Proesi/Seel: No dataProduct at all (images are in HTML gallery).
        """
        result = {}

        # Tentar extrair o JSON completo primeiro
        patterns = [
            r'window\.dataProduct\s*=\s*({[\s\S]*?});?\s*(?:window\.|</script>)',
            r'const\s+dataProduct\s*=\s*({[\s\S]*?});?\s*(?:</script>)',
            r'dataProduct\s*=\s*({[\s\S]*?});?\s*(?:window\.|</script>)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                try:
                    json_str = match.group(1)
                    json_str = re.sub(r',\s*}', '}', json_str)
                    json_str = re.sub(r',\s*]', ']', json_str)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

        # Fallback: extrair o campo produto JSON de dentro de dataProduct
        # (formato JS com chaves não-quoted: { id: '...', produto: {...} })
        # Usa busca por brace-matching para extrair o JSON completo do produto
        prod_start_match = re.search(r'(?:const|var|window\.)\s*dataProduct\s*=\s*\{[^}]*?produto:\s*(\{"produto_id")', html_content)
        if prod_start_match:
            json_start = prod_start_match.start(1)
            brace_count = 0
            i = json_start
            while i < len(html_content):
                if html_content[i] == '{':
                    brace_count += 1
                elif html_content[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        try:
                            produto_data = json.loads(html_content[json_start:json_end])
                            result['produto'] = produto_data
                        except json.JSONDecodeError:
                            pass
                        break
                i += 1

        # Fallback: extrair campos individuais (formato JS não-JSON)
        if not result:
            # Extrair breadcrumb
            bc_match = re.search(r'breadcrumb:\s*(\[[\s\S]*?\])\s*,', html_content)
            if bc_match:
                try:
                    result['breadcrumb'] = json.loads(bc_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Extrair produto (JSON embedded antes de derivacao)
            prod_match = re.search(r'produto:\s*(\{"produto_id"[\s\S]*?\})\s*,\s*derivacao:', html_content)
            if prod_match:
                try:
                    result['produto'] = json.loads(prod_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Extrair derivacao (contém preço e estoque)
            deriv_match = re.search(r'derivacao:\s*(\{[\s\S]*?"preco"[\s\S]*?\})\s*,\s*(?:breadcrumb|depositos):', html_content)
            if deriv_match:
                try:
                    result['derivacao'] = json.loads(deriv_match.group(1))
                except json.JSONDecodeError:
                    pass

        return result if result else None

    def _extract_json_ld(self, soup: BeautifulSoup) -> Optional[dict]:
        """Extrai dados JSON-LD do Schema.org"""
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Product':
                    return data
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Product':
                            return item
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _get_cdn_base(self) -> str:
        """Retorna a URL base do CDN Magazord para este fornecedor.

        Padrão: https://{subdomain}.cdn.magazord.com.br/
        Ex: https://www.lojavale.com.br -> https://lojavale.cdn.magazord.com.br/
            https://www.proesi.com.br -> https://proesi.cdn.magazord.com.br/
            https://www.seeldistribuidora.com.br -> https://seeldistribuidora.cdn.magazord.com.br/
        """
        # Extrair subdomain do base_url
        parsed = urlparse(self.base_url)
        hostname = parsed.hostname or ''
        # Remover 'www.' do início
        subdomain = hostname.replace('www.', '').split('.')[0]
        return f"https://{subdomain}.cdn.magazord.com.br/"

    def _clean_text(self, text: Optional[str]) -> Optional[str]:
        """Limpa texto removendo tags HTML e espaços extras"""
        if not text:
            return None
        # Remover tags HTML
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decodificar entidades HTML
        text = html.unescape(text)
        # Normalizar espaços
        text = re.sub(r'\s+', ' ', text).strip()
        return text if text else None

    def parse_product(self, url: str) -> Optional[Product]:
        """Parse de página de produto Magazord"""
        html_content = self.fetch(url)
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')

        try:
            # Tentar extrair dados estruturados
            data_product = self._extract_data_product(html_content)
            json_ld = self._extract_json_ld(soup)

            # Nome do produto
            name = None
            if data_product and data_product.get('produto', {}).get('nome'):
                name = data_product['produto']['nome']
            elif json_ld and json_ld.get('name'):
                name = json_ld['name']
            else:
                name_el = soup.select_one('h1.product-name, h1[itemprop="name"], .product-title h1, h1')
                name = name_el.get_text(strip=True) if name_el else None

            if not name:
                return None

            # SKU
            sku = None
            if data_product:
                sku = data_product.get('produto', {}).get('referencia')
                if not sku:
                    sku = str(data_product.get('derivacao', {}).get('id', ''))
            if not sku and json_ld:
                sku = json_ld.get('sku')
            if not sku:
                sku_el = soup.select_one('.caract-referencia dd, [itemprop="sku"], .product-sku')
                if sku_el:
                    sku = sku_el.get_text(strip=True)
            if not sku:
                # Gerar a partir da URL
                sku = url.split('/')[-1][:50]

            # Preço
            price = None
            price_pix = None
            if data_product:
                # Formato antigo: derivacao.preco
                preco_data = data_product.get('derivacao', {}).get('preco', {})
                price = preco_data.get('precoPor') or preco_data.get('precoDe')
                price_pix = preco_data.get('precoPix')

                # Formato Loja Vale: produto.valor (string ou float)
                if not price:
                    valor = data_product.get('produto', {}).get('valor')
                    if valor:
                        try:
                            price = float(str(valor).replace(',', '.'))
                        except (ValueError, TypeError):
                            pass

            if not price:
                # Tentar meta tags
                price_meta = soup.select_one('meta[property="product:price:amount"], meta[property="og:price:amount"]')
                if price_meta and price_meta.get('content'):
                    try:
                        price = float(price_meta['content'].replace(',', '.'))
                    except ValueError:
                        pass

            if not price and json_ld:
                offers = json_ld.get('offers', {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price_str = offers.get('price')
                if price_str:
                    try:
                        price = float(str(price_str).replace(',', '.'))
                    except ValueError:
                        pass

            if not price:
                return None

            # Estoque
            stock = None
            in_stock = True
            if data_product:
                # Formato antigo: derivacao.estoque
                estoque = data_product.get('derivacao', {}).get('estoque', {})
                stock = estoque.get('quantidade')
                in_stock = estoque.get('disponivel', True)

                # Formato Loja Vale: produto.qtde_estoque
                if stock is None:
                    qtde = data_product.get('produto', {}).get('qtde_estoque')
                    if qtde is not None:
                        try:
                            stock = int(qtde)
                            in_stock = stock > 0
                        except (ValueError, TypeError):
                            pass

            if in_stock and json_ld:
                # Verificar JSON-LD como complemento
                availability = json_ld.get('offers', {}).get('availability', '')
                if 'OutOfStock' in availability:
                    in_stock = False

            if not data_product and not stock and json_ld:
                availability = json_ld.get('offers', {}).get('availability', '')
                in_stock = 'InStock' in availability

            # Marca
            brand = None
            if data_product:
                marca_data = data_product.get('produto', {}).get('marca')
                if isinstance(marca_data, dict):
                    brand = marca_data.get('nome')
                elif isinstance(marca_data, str) and marca_data:
                    brand = marca_data
            if not brand and json_ld:
                brand_data = json_ld.get('brand', {})
                brand = brand_data.get('name') if isinstance(brand_data, dict) else brand_data
            if not brand:
                brand_el = soup.select_one('[itemprop="brand"], .product-brand, .marca')
                if brand_el:
                    brand = brand_el.get_text(strip=True)

            # Imagens
            image = None
            images = []

            # 1. Tentar derivacao.imagens (formato antigo Magazord)
            if data_product:
                imagens = data_product.get('derivacao', {}).get('imagens', [])
                for img in imagens:
                    img_url = img.get('maior') or img.get('media') or img.get('menor')
                    if img_url and img_url not in images:
                        images.append(img_url)

            # 2. Tentar produto.midias[] (formato Loja Vale / Magazord React)
            #    Cada midia tem midia_path e midia_arquivo_nome que formam a URL CDN
            if not images and data_product:
                produto_data = data_product.get('produto', {})
                midias = produto_data.get('midias', [])
                if midias:
                    # Detectar CDN base a partir do base_url do fornecedor
                    # Ex: https://www.lojavale.com.br -> https://lojavale.cdn.magazord.com.br/
                    cdn_base = self._get_cdn_base()
                    for midia in midias:
                        if midia.get('tipo_midia') == 1:  # tipo_midia 1 = imagem
                            mpath = midia.get('midia_path', '')
                            mnome = midia.get('midia_arquivo_nome', '')
                            if mpath and mnome:
                                img_url = f"{cdn_base}{mpath}{mnome}"
                                if img_url not in images:
                                    images.append(img_url)
                    # Se nenhum tipo_midia==1, tentar todos
                    if not images:
                        for midia in midias:
                            mpath = midia.get('midia_path', '')
                            mnome = midia.get('midia_arquivo_nome', '')
                            if mpath and mnome:
                                img_url = f"{cdn_base}{mpath}{mnome}"
                                if img_url not in images:
                                    images.append(img_url)
                # Fallback: midia_path/midia_arquivo_nome no nível do produto
                if not images:
                    mpath = produto_data.get('midia_path', '')
                    mnome = produto_data.get('midia_arquivo_nome', '')
                    if mpath and mnome:
                        cdn_base = self._get_cdn_base()
                        img_url = f"{cdn_base}{mpath}{mnome}"
                        images.append(img_url)

            # 3. Extrair da galeria HTML (Proesi, Seel, e outros Magazord)
            #    O swiper gallery-thumbs contém thumbnails com data-img-full
            #    que apontam para a imagem em resolução máxima (sem resize params)
            if not images:
                gallery_slides = soup.select('.gallery-thumbs .swiper-slide a[data-img-full]')
                for slide in gallery_slides:
                    img_url = slide.get('data-img-full', '').strip()
                    if img_url and img_url.startswith('http') and img_url not in images:
                        images.append(img_url)

            # 4. Fallback: imagens no gallery-main (data-img-full ou data-src-max)
            if not images:
                gallery_main_imgs = soup.select('.gallery-main .swiper-slide img[data-img-full]')
                for img_el in gallery_main_imgs:
                    img_url = img_el.get('data-img-full', '').strip()
                    if img_url and img_url.startswith('http') and img_url not in images:
                        images.append(img_url)
                if not images:
                    gallery_main_imgs = soup.select('.gallery-main .swiper-slide img[data-src-max]')
                    for img_el in gallery_main_imgs:
                        img_url = img_el.get('data-src-max', '').strip()
                        if img_url and img_url.startswith('http') and img_url not in images:
                            images.append(img_url)

            # 5. Fallback: JSON-LD images (pode ter array de URLs)
            if not images and json_ld:
                ld_images = json_ld.get('image', [])
                if isinstance(ld_images, str):
                    ld_images = [ld_images]
                for img_url in ld_images:
                    if img_url and img_url not in images:
                        images.append(img_url)

            # 6. Fallback para meta og:image
            if not images:
                og_image = soup.select_one('meta[property="og:image"]')
                if og_image and og_image.get('content'):
                    images.append(og_image['content'])

            # 7. Fallback para imagens genéricas no HTML
            if not images:
                img_elements = soup.select('[itemprop="image"], .product-image img, .gallery-image img')
                for img_el in img_elements:
                    img_url = img_el.get('data-src-max') or img_el.get('data-src') or img_el.get('src')
                    if img_url and img_url.startswith('http') and img_url not in images:
                        images.append(img_url)

            image = images[0] if images else None

            # Descrição
            description = None
            if data_product:
                description = data_product.get('produto', {}).get('descricao')

            if not description:
                desc_el = soup.select_one('#descricao-produto .content, .descricao-produto .content, [itemprop="description"]')
                if desc_el:
                    description = desc_el.get_text(strip=True)

            if not description:
                meta_desc = soup.select_one('meta[name="description"]')
                if meta_desc and meta_desc.get('content'):
                    description = meta_desc['content']

            description = self._clean_text(description)
            if description and len(description) > 3000:
                description = description[:2997] + '...'

            # Categoria
            category = None
            category_path = []

            if data_product:
                # Tentar categorizacoes primeiro
                cats = data_product.get('produto', {}).get('categorizacoes', [])
                if cats:
                    cat_names = [c.get('nome') for c in cats if c.get('nome')]
                    category_path = cat_names
                    if cat_names:
                        category = cat_names[-1].lower().replace(' ', '-')

                # Se não tiver categorizacoes, tentar breadcrumb do dataProduct
                if not category_path:
                    breadcrumb_data = data_product.get('breadcrumb', [])
                    if breadcrumb_data:
                        # Pular "Home" (primeiro item)
                        cat_names = [b.get('nome') for b in breadcrumb_data[1:] if b.get('nome') and b.get('nome') != 'Home']
                        category_path = cat_names
                        if cat_names:
                            category = cat_names[-1].lower().replace(' ', '-')

            # Fallback: extrair do HTML
            if not category_path:
                breadcrumb = soup.select('.breadcrumb a, .breadcrumbs a, nav[aria-label="breadcrumb"] a')
                if breadcrumb:
                    category_path = [a.get_text(strip=True) for a in breadcrumb[1:]]
                    if category_path:
                        category = category_path[-1].lower().replace(' ', '-')

            # Especificações (características)
            specs = {}
            carac_section = soup.select_one('#caracteristicas .grupo-carac, #caracteristicas dl, .caracteristicas-produto')
            if carac_section:
                dts = carac_section.select('dt')
                dds = carac_section.select('dd')
                for dt, dd in zip(dts, dds):
                    key = dt.get_text(strip=True)
                    value = dd.get_text(strip=True)
                    if key and value and key.lower() not in ('referência', 'sku'):
                        specs[key] = value

            # Datasheet
            datasheet = None
            datasheet_el = soup.select_one('a[href*="datasheet"], a[href*="manual"], a[href$=".pdf"]')
            if datasheet_el:
                datasheet = datasheet_el.get('href')
                if datasheet and not datasheet.startswith('http'):
                    datasheet = urljoin(self.base_url, datasheet)

            # Garantia
            warranty = None
            if data_product:
                warranty = data_product.get('produto', {}).get('garantias')
            if not warranty:
                # Fallback: procurar no HTML
                warranty_el = soup.select_one('.garantia, [class*="warranty"], [class*="garantia"]')
                if warranty_el:
                    warranty = warranty_el.get_text(strip=True)

            # Vídeos (Loja Vale / Magazord)
            videos = []
            video_elements = soup.select('.video-mini[data-url-video]')
            for video_el in video_elements:
                video_url = video_el.get('data-url-video', '').strip()
                if video_url:
                    # Detectar plataforma
                    platform = 'unknown'
                    if 'youtube.com' in video_url or 'youtu.be' in video_url:
                        platform = 'youtube'
                        # Extrair video ID do YouTube
                        yt_match = re.search(r'(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
                        if yt_match:
                            video_url = f'https://www.youtube.com/embed/{yt_match.group(1)}'
                    elif 'vimeo.com' in video_url:
                        platform = 'vimeo'
                        # Garantir formato embed do Vimeo
                        vimeo_match = re.search(r'vimeo\.com/(?:video/)?(\d+)', video_url)
                        if vimeo_match:
                            video_url = f'https://player.vimeo.com/video/{vimeo_match.group(1)}'

                    # Evitar duplicatas
                    if not any(v['url'] == video_url for v in videos):
                        videos.append({
                            'url': video_url,
                            'platform': platform
                        })

            # Slug
            slug = url.replace(self.base_url, '').strip('/')

            # Gerar ID único
            product_id = f"{self.id_prefix}{sku}"

            return Product(
                id=product_id,
                sku=sku,
                name=name,
                slug=slug,
                brand=brand,
                price=price,
                priceFormatted=f"R$ {price:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
                pricePix=price_pix,
                stock=stock,
                inStock=in_stock,
                description=description,
                specs=specs if specs else None,
                category=category,
                categoryPath=category_path if category_path else None,
                image=image,
                images=images if images else None,
                videos=videos if videos else None,
                datasheet=datasheet,
                warranty=warranty,
                sourceUrl=url,
                supplier=self.source_name
            )

        except Exception as e:
            logger.error(f"Erro ao processar {url}: {e}")
            return None


def save_products(products: list[Product], sources: list[str]):
    """Salva produtos no arquivo JSON"""
    # Carregar produtos existentes de outros fornecedores
    existing_products = []
    if PRODUCTS_FILE.exists():
        try:
            with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                # Manter produtos de fornecedores que não estamos atualizando
                for p in old_data.get('products', []):
                    if p.get('supplier') not in [SUPPLIERS[s]['name'] for s in sources]:
                        existing_products.append(p)
        except json.JSONDecodeError:
            pass

    # Converter produtos para dicionários
    new_products = [p.to_dict() for p in products]

    # Combinar produtos existentes com novos
    all_products = existing_products + new_products

    # Ordenar por nome
    all_products.sort(key=lambda x: x.get('name', ''))

    # Gerar categorias (diretamente dos dicts)
    category_counts = {}
    for p in all_products:
        if p.get('category'):
            cat = p['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1

    categories = [
        {'id': cat_id, 'name': cat_id.replace('-', ' ').title(), 'count': count}
        for cat_id, count in sorted(category_counts.items(), key=lambda x: -x[1])
    ]

    # Montar dados finais
    supplier_names = list(set(p.get('supplier', 'Desconhecido') for p in all_products))
    data = {
        'lastUpdated': datetime.now(timezone.utc).isoformat(),
        'sources': supplier_names,
        'totalProducts': len(all_products),
        'products': all_products,
        'categories': categories
    }

    # Salvar
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Salvos {len(all_products)} produtos em {PRODUCTS_FILE}")

    return len(new_products)


def export_mercadolivre(products: list[dict], output_file: Path):
    """Exporta produtos para formato Mercado Livre (CSV)"""
    headers = [
        'titulo', 'descricao', 'preco', 'quantidade', 'condicao',
        'marca', 'modelo_sku', 'gtin', 'imagem_principal', 'imagens_adicionais',
        'categoria', 'peso_kg', 'comprimento_cm', 'largura_cm', 'altura_cm'
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for p in products:
            # Título máximo 60 caracteres
            title = p.get('name', '')[:60]
            # Descrição máximo 50000 caracteres
            desc = (p.get('description') or '')[:50000]

            images = p.get('images') or []
            additional_images = '|'.join(images[1:6]) if len(images) > 1 else ''

            dims = p.get('dimensions_cm') or {}

            row = [
                title,
                desc,
                p.get('price', 0),
                p.get('stock') or 1,
                'new',
                p.get('brand') or 'Genérico',
                p.get('sku', ''),
                p.get('gtin') or '',
                p.get('image', ''),
                additional_images,
                ' > '.join(p.get('categoryPath') or [p.get('category', '')]),
                p.get('weight_kg') or 0.5,
                dims.get('length', 20),
                dims.get('width', 15),
                dims.get('height', 10)
            ]
            writer.writerow(row)

    logger.info(f"Exportados {len(products)} produtos para {output_file} (Mercado Livre)")


def export_shopee(products: list[dict], output_file: Path):
    """Exporta produtos para formato Shopee (CSV)"""
    headers = [
        'nome', 'descricao', 'preco', 'estoque', 'marca', 'modelo',
        'peso', 'comprimento', 'largura', 'altura',
        'imagem_1', 'imagem_2', 'imagem_3', 'imagem_4', 'imagem_5',
        'categoria'
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for p in products:
            # Nome máximo 120 caracteres
            name = p.get('name', '')[:120]
            # Descrição máximo 3000 caracteres
            desc = (p.get('description') or '')[:3000]

            images = [p.get('image', '')] + (p.get('images') or [])
            images = images[:5]  # Máximo 5 imagens
            while len(images) < 5:
                images.append('')

            dims = p.get('dimensions_cm') or {}

            row = [
                name,
                desc,
                p.get('price', 0),
                p.get('stock') or 0,
                p.get('brand') or '',
                p.get('sku', ''),
                p.get('weight_kg') or 0.5,
                dims.get('length', 10),
                dims.get('width', 10),
                dims.get('height', 10),
                images[0], images[1], images[2], images[3], images[4],
                ' > '.join(p.get('categoryPath') or [p.get('category', '')])
            ]
            writer.writerow(row)

    logger.info(f"Exportados {len(products)} produtos para {output_file} (Shopee)")


def main():
    parser = argparse.ArgumentParser(description='Scraper de produtos - Blumenau Automação')
    parser.add_argument('--source', choices=['proesi', 'lojavale', 'seel', 'all'],
                        default='all', help='Fonte de produtos (default: all)')
    parser.add_argument('--test', action='store_true',
                        help='Modo teste (processa só 10 produtos por fonte)')
    parser.add_argument('--min-price', type=float, default=100.0,
                        help='Preço mínimo em R$ (default: 100)')
    parser.add_argument('--delay', type=float, default=0.3,
                        help='Delay entre requests em segundos (default: 0.3)')
    parser.add_argument('--workers', type=int, default=8,
                        help='Número de workers paralelos (default: 8)')
    parser.add_argument('--incremental', action='store_true',
                        help='Modo incremental - só baixa produtos alterados')
    parser.add_argument('--resume', action='store_true',
                        help='Continuar de onde parou (não reinicia do zero)')
    parser.add_argument('--reset', action='store_true',
                        help='Resetar progresso e começar do zero')
    parser.add_argument('--status', action='store_true',
                        help='Mostrar status do progresso atual')
    parser.add_argument('--export', choices=['mercadolivre', 'shopee'],
                        help='Exportar para marketplace')
    parser.add_argument('-o', '--output', type=str,
                        help='Arquivo de saída para exportação')
    args = parser.parse_args()

    # Inicializar banco de dados
    db = ProductsDB()

    # Se for apenas status
    if args.status:
        print("\n=== Status do Scraper ===\n")
        for source in ['proesi', 'lojavale', 'seel']:
            progress = db.get_progress(SUPPLIERS[source]['name'])
            print(f"{SUPPLIERS[source]['name']}:")
            print(f"  Total: {progress['total']}")
            print(f"  Concluídos: {progress['done']}")
            print(f"  Pendentes: {progress['pending']}")
            print(f"  Erros: {progress['errors']}")
            print()
        return 0

    # Se for reset
    if args.reset:
        for source in ['proesi', 'lojavale', 'seel']:
            db.reset_urls(SUPPLIERS[source]['name'])
        print("Progresso resetado com sucesso!")
        return 0

    # Se for exportação, apenas exportar
    if args.export:
        if not PRODUCTS_FILE.exists():
            logger.error(f"Arquivo {PRODUCTS_FILE} não encontrado. Execute o scraper primeiro.")
            return 1

        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        products = data.get('products', [])
        output_file = Path(args.output) if args.output else BASE_DIR / f"export_{args.export}.csv"

        if args.export == 'mercadolivre':
            export_mercadolivre(products, output_file)
        elif args.export == 'shopee':
            export_shopee(products, output_file)

        return 0

    # Determinar fontes a processar
    # Ordem: Loja Vale e Seel primeiro (mais produtos caros), Proesi por último
    if args.source == 'all':
        sources = ['lojavale', 'seel', 'proesi']
    else:
        sources = [args.source]

    logger.info(f"Iniciando scraper - Fontes: {', '.join(sources)}, Preço mínimo: R$ {args.min_price}")
    logger.info(f"Workers: {args.workers}, Delay: {args.delay}s, Resume: {args.resume}")

    all_products = []

    for source in sources:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processando: {SUPPLIERS[source]['name']}")
        logger.info(f"{'='*50}")

        # Mostrar progresso atual
        progress = db.get_progress(SUPPLIERS[source]['name'])
        if progress['total'] > 0:
            logger.info(f"Progresso anterior: {progress['done']}/{progress['total']} ({progress['pending']} pendentes)")

        scraper = MagazordScraper(
            source,
            min_price=args.min_price,
            delay=args.delay,
            workers=args.workers
        )

        limit = 10 if args.test else None

        # Callback para salvar incrementalmente
        def incremental_save(prods, src):
            save_products(prods, [source])

        products = scraper.scrape_all(
            limit=limit,
            db=db,
            incremental=args.incremental,
            resume=args.resume,
            save_callback=incremental_save,
            save_interval=25  # Salvar a cada 25 produtos
        )

        if products:
            all_products.extend(products)
            logger.info(f"Obtidos {len(products)} produtos de {SUPPLIERS[source]['name']}")
        else:
            logger.warning(f"Nenhum produto novo encontrado em {SUPPLIERS[source]['name']}")

    if not all_products:
        logger.warning("Nenhum produto encontrado em nenhuma fonte!")
        return 1

    # Salvar resultados
    total_saved = save_products(all_products, sources)

    logger.info(f"\n{'='*50}")
    logger.info(f"CONCLUÍDO!")
    logger.info(f"Total de produtos novos/atualizados: {len(all_products)}")
    logger.info(f"Arquivo: {PRODUCTS_FILE}")
    logger.info(f"{'='*50}")

    return 0


if __name__ == '__main__':
    exit(main())
