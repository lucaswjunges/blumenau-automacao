#!/usr/bin/env python3
"""
Blumenau Automação - Exportador para Mercado Livre
Gera CSV para importação em massa no ML com preços ajustados para lucro zero.

Uso:
    python scripts/mercadolivre_export.py

O script lê products.json e gera mercadolivre_products.csv
"""

import json
import csv
import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

# =============================================================================
# CONFIGURAÇÃO DE TAXAS DO MERCADO LIVRE
# =============================================================================

# Taxas por categoria (aproximadas - verificar no ML para sua categoria específica)
# https://www.mercadolivre.com.br/ajuda/quanto-custa-vender-um-produto_1338
ML_FEES = {
    'default': 0.13,           # 13% padrão para maioria das categorias
    'eletronicos': 0.14,       # 14% eletrônicos
    'informatica': 0.13,       # 13% informática
    'ferramentas': 0.12,       # 12% ferramentas
    'industria': 0.11,         # 11% industrial
    'automacao': 0.13,         # 13% automação
}

# Taxa fixa para vendas abaixo de R$ 79
ML_FIXED_FEE_THRESHOLD = 79.00
ML_FIXED_FEE = 6.00  # R$ 6,00 para vendas < R$ 79

# Margem de segurança (para cobrir variações e arredondamentos)
SAFETY_MARGIN = 0.02  # 2% extra

# =============================================================================
# MAPEAMENTO DE CATEGORIAS
# =============================================================================

def get_ml_category_fee(product: dict) -> float:
    """Determina a taxa do ML baseado na categoria do produto."""
    category = (product.get('category', '') or '').lower()
    category_path = ' '.join(product.get('categoryPath', []) or []).lower()

    full_category = f"{category} {category_path}"

    if any(term in full_category for term in ['arduino', 'esp32', 'raspberry', 'microcontrolador', 'placa']):
        return ML_FEES['eletronicos']
    elif any(term in full_category for term in ['clp', 'plc', 'inversor', 'servo', 'automação', 'industrial']):
        return ML_FEES['industria']
    elif any(term in full_category for term in ['alicate', 'chave', 'ferramenta', 'solda']):
        return ML_FEES['ferramentas']
    elif any(term in full_category for term in ['cabo', 'fio', 'conector', 'sensor']):
        return ML_FEES['informatica']

    return ML_FEES['default']


def calculate_ml_price(cost_price: float, category_fee: float) -> float:
    """
    Calcula o preço de venda no ML para lucro zero.

    Fórmula: PreçoML = Custo / (1 - Taxa% - MargemSegurança%)

    Se preço < R$ 79, adiciona taxa fixa ao cálculo.
    """
    # Primeiro cálculo sem taxa fixa
    total_fee = category_fee + SAFETY_MARGIN
    ml_price = cost_price / (1 - total_fee)

    # Se preço ficou abaixo de R$ 79, precisa considerar taxa fixa
    if ml_price < ML_FIXED_FEE_THRESHOLD:
        # PreçoML = (Custo + TaxaFixa) / (1 - Taxa%)
        ml_price = (cost_price + ML_FIXED_FEE) / (1 - total_fee)

    # Arredonda para cima para o próximo centavo
    return round(ml_price + 0.005, 2)


def calculate_profit(ml_price: float, cost_price: float, category_fee: float) -> float:
    """Calcula o lucro real após taxas do ML."""
    if ml_price < ML_FIXED_FEE_THRESHOLD:
        ml_commission = (ml_price * category_fee) + ML_FIXED_FEE
    else:
        ml_commission = ml_price * category_fee

    profit = ml_price - ml_commission - cost_price
    return round(profit, 2)


# =============================================================================
# FORMATAÇÃO PARA MERCADO LIVRE
# =============================================================================

def clean_title(name: str, max_length: int = 60) -> str:
    """Limpa e trunca o título para o limite do ML (60 caracteres)."""
    # Remove espaços extras
    name = ' '.join(name.split())
    # Remove caracteres especiais problemáticos
    name = re.sub(r'[|\\/<>]', ' ', name)
    name = ' '.join(name.split())

    if len(name) <= max_length:
        return name

    # Trunca de forma inteligente (não corta palavras)
    truncated = name[:max_length-3].rsplit(' ', 1)[0] + '...'
    return truncated


def clean_description(description: str, product: dict) -> str:
    """Formata a descrição para o ML."""
    if not description:
        description = f"Produto: {product.get('name', 'Sem nome')}"

    # Remove HTML tags
    description = re.sub(r'<[^>]+>', ' ', description)
    # Remove múltiplos espaços/quebras
    description = ' '.join(description.split())

    # Adiciona informações extras
    extras = []
    if product.get('brand'):
        extras.append(f"Marca: {product['brand']}")
    if product.get('warranty'):
        extras.append(f"Garantia: {product['warranty']}")
    if product.get('sku'):
        extras.append(f"SKU: {product['sku']}")

    if extras:
        description += "\n\n" + "\n".join(extras)

    # Adiciona aviso padrão
    description += "\n\n---\nProduto novo, com nota fiscal.\nEnvio imediato após confirmação do pagamento."

    return description[:50000]  # Limite ML


def get_ml_category_id(product: dict) -> str:
    """
    Retorna o ID da categoria do ML.

    Nota: Você precisará mapear para as categorias reais do ML.
    Use: https://api.mercadolibre.com/sites/MLB/categories
    """
    # Mapeamento básico - você deve ajustar para suas categorias específicas
    category = (product.get('category', '') or '').lower()
    category_path = product.get('categoryPath', []) or []

    # IDs de exemplo - substitua pelos corretos do ML
    category_mapping = {
        'arduino': 'MLB1648',      # Componentes Eletrônicos
        'esp32': 'MLB1648',
        'raspberry': 'MLB1648',
        'sensor': 'MLB1648',
        'cabo': 'MLB1648',
        'ferramenta': 'MLB278936',  # Ferramentas
        'alicate': 'MLB278936',
        'multimetro': 'MLB278936',
        'inversor': 'MLB1648',
        'clp': 'MLB1648',
        'plc': 'MLB1648',
        'rele': 'MLB1648',
        'fonte': 'MLB1648',
        'conector': 'MLB1648',
    }

    full_text = f"{category} {' '.join(category_path)}".lower()

    for key, cat_id in category_mapping.items():
        if key in full_text:
            return cat_id

    return 'MLB1648'  # Categoria padrão: Componentes Eletrônicos


# =============================================================================
# EXPORTAÇÃO PRINCIPAL
# =============================================================================

def export_to_mercadolivre(products_file: str, output_file: str):
    """Exporta produtos para CSV do Mercado Livre."""

    # Carrega produtos
    with open(products_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    products = data.get('products', [])

    # Filtra apenas produtos em estoque e com preço válido
    valid_products = [
        p for p in products
        if p.get('inStock', False) and p.get('price', 0) > 0
    ]

    print(f"Total de produtos: {len(products)}")
    print(f"Produtos válidos (em estoque): {len(valid_products)}")

    # Estatísticas
    stats = {
        'total': len(valid_products),
        'total_cost': 0,
        'total_ml_price': 0,
        'total_profit': 0,
        'by_supplier': {}
    }

    # Prepara dados para CSV
    ml_products = []

    for product in valid_products:
        cost_price = product.get('price', 0)
        if cost_price <= 0:
            continue

        category_fee = get_ml_category_fee(product)
        ml_price = calculate_ml_price(cost_price, category_fee)
        profit = calculate_profit(ml_price, cost_price, category_fee)

        # Atualiza estatísticas
        stats['total_cost'] += cost_price
        stats['total_ml_price'] += ml_price
        stats['total_profit'] += profit

        supplier = product.get('supplier', 'Desconhecido')
        if supplier not in stats['by_supplier']:
            stats['by_supplier'][supplier] = {'count': 0, 'cost': 0, 'ml_price': 0}
        stats['by_supplier'][supplier]['count'] += 1
        stats['by_supplier'][supplier]['cost'] += cost_price
        stats['by_supplier'][supplier]['ml_price'] += ml_price

        ml_product = {
            # Campos obrigatórios do ML
            'titulo': clean_title(product.get('name', '')),
            'preco': ml_price,
            'preco_custo': cost_price,
            'lucro_estimado': profit,
            'quantidade': 10,  # Estoque padrão
            'condicao': 'new',  # new ou used
            'tipo_anuncio': 'gold_special',  # classico, gold_special, gold_pro
            'categoria_ml': get_ml_category_id(product),

            # Dados do produto
            'sku': product.get('sku', product.get('id', '')),
            'marca': product.get('brand', 'Genérico'),
            'descricao': clean_description(product.get('description', ''), product),

            # Imagens (até 10)
            'imagem_1': product.get('image', ''),
            'imagem_2': '',
            'imagem_3': '',

            # Frete
            'frete_gratis': 'Não',  # Sim ou Não
            'tipo_frete': 'me2',  # me1 (Correios), me2 (Mercado Envios Full)

            # Dados internos (para referência)
            'fornecedor': product.get('supplier', ''),
            'url_fornecedor': product.get('sourceUrl', ''),
            'categoria_original': ' > '.join(product.get('categoryPath', []) or []),
            'taxa_ml': f"{category_fee*100:.1f}%",
        }

        ml_products.append(ml_product)

    # Ordena por fornecedor e preço
    ml_products.sort(key=lambda x: (x['fornecedor'], x['preco']))

    # Exporta para CSV
    if ml_products:
        fieldnames = ml_products[0].keys()

        with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            writer.writerows(ml_products)

    # Imprime relatório
    print("\n" + "="*60)
    print("RELATÓRIO DE EXPORTAÇÃO MERCADO LIVRE")
    print("="*60)
    print(f"\nArquivo gerado: {output_file}")
    print(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"\nProdutos exportados: {stats['total']}")
    print(f"\nValores totais:")
    print(f"  Custo (fornecedor):  R$ {stats['total_cost']:,.2f}")
    print(f"  Preço ML:            R$ {stats['total_ml_price']:,.2f}")
    print(f"  Lucro estimado:      R$ {stats['total_profit']:,.2f}")
    print(f"  Markup médio:        {((stats['total_ml_price']/stats['total_cost'])-1)*100:.1f}%")

    print(f"\nPor fornecedor:")
    for supplier, data in sorted(stats['by_supplier'].items()):
        markup = ((data['ml_price']/data['cost'])-1)*100 if data['cost'] > 0 else 0
        print(f"  {supplier}:")
        print(f"    Produtos: {data['count']}")
        print(f"    Custo total: R$ {data['cost']:,.2f}")
        print(f"    Preço ML total: R$ {data['ml_price']:,.2f}")
        print(f"    Markup: {markup:.1f}%")

    print("\n" + "="*60)
    print("EXEMPLO DE CÁLCULO")
    print("="*60)
    if ml_products:
        example = ml_products[0]
        print(f"\nProduto: {example['titulo'][:50]}...")
        print(f"  Custo (fornecedor): R$ {example['preco_custo']:.2f}")
        print(f"  Taxa ML: {example['taxa_ml']}")
        print(f"  Preço no ML: R$ {example['preco']:.2f}")
        print(f"  Lucro estimado: R$ {example['lucro_estimado']:.2f}")

    print("\n" + "="*60)
    print("PRÓXIMOS PASSOS")
    print("="*60)
    print("""
1. Acesse: https://www.mercadolivre.com.br/vendas/publicacoes/carregamento-massivo
2. Baixe o template do ML para sua categoria
3. Copie os dados do CSV gerado para o template
4. Ajuste as categorias específicas do ML
5. Faça upload do arquivo

IMPORTANTE:
- Verifique as categorias do ML para seus produtos
- Ajuste as taxas se necessário (variam por categoria)
- O preço foi calculado para lucro ~0 (cobrir taxas)
- Considere ativar frete grátis para aumentar vendas
""")

    return ml_products


# =============================================================================
# GERADOR DE PLANILHA SIMPLIFICADA
# =============================================================================

def export_simple_csv(products_file: str, output_file: str):
    """
    Gera uma planilha simplificada para copiar/colar no ML.
    Formato mais fácil de usar manualmente.
    """
    with open(products_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    products = data.get('products', [])
    valid_products = [
        p for p in products
        if p.get('inStock', False) and p.get('price', 0) > 0
    ]

    output_simple = output_file.replace('.csv', '_simples.csv')

    with open(output_simple, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')

        # Cabeçalho simples
        writer.writerow([
            'Título (max 60 chars)',
            'Preço Custo',
            'Preço ML (lucro 0)',
            'Markup %',
            'SKU',
            'Marca',
            'Fornecedor',
            'Link Imagem',
            'Link Fornecedor'
        ])

        for product in valid_products:
            cost = product.get('price', 0)
            if cost <= 0:
                continue

            fee = get_ml_category_fee(product)
            ml_price = calculate_ml_price(cost, fee)
            markup = ((ml_price / cost) - 1) * 100

            writer.writerow([
                clean_title(product.get('name', '')),
                f"R$ {cost:.2f}",
                f"R$ {ml_price:.2f}",
                f"{markup:.1f}%",
                product.get('sku', product.get('id', '')),
                product.get('brand', ''),
                product.get('supplier', ''),
                product.get('image', ''),
                product.get('sourceUrl', '')
            ])

    print(f"\nPlanilha simplificada: {output_simple}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    import sys

    # Caminhos
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent

    products_file = project_dir / 'products.json'
    output_file = project_dir / 'mercadolivre_products.csv'

    if not products_file.exists():
        print(f"Erro: Arquivo {products_file} não encontrado!")
        sys.exit(1)

    print("="*60)
    print("EXPORTADOR MERCADO LIVRE - BLUMENAU AUTOMAÇÃO")
    print("="*60)

    # Exporta CSV completo
    export_to_mercadolivre(str(products_file), str(output_file))

    # Exporta versão simplificada
    export_simple_csv(str(products_file), str(output_file))

    print("\n✅ Exportação concluída!")
