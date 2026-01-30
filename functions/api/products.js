/**
 * Blumenau Automação - Products API
 *
 * GET /api/products - Lista todos os produtos
 * GET /api/products?id=123 - Retorna produto específico
 * GET /api/products?category=encoder - Filtra por categoria
 * GET /api/products?format=google - Retorna feed para Google Shopping
 * GET /api/products?format=csv - Retorna CSV para marketplaces
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

/**
 * Handler GET - Lista produtos
 */
export async function onRequestGet(context) {
  const { request } = context;
  const url = new URL(request.url);

  const id = url.searchParams.get('id');
  const category = url.searchParams.get('category');
  const format = url.searchParams.get('format');
  const inStock = url.searchParams.get('inStock');

  try {
    // Busca products.json do próprio site
    const siteUrl = url.origin;
    const productsResponse = await fetch(`${siteUrl}/products.json`);

    if (!productsResponse.ok) {
      throw new Error('Erro ao carregar produtos');
    }

    const data = await productsResponse.json();
    let products = data.products || [];

    // Filtro por ID
    if (id) {
      const product = products.find(p => p.id === id || p.sku === id);
      if (!product) {
        return new Response(
          JSON.stringify({ success: false, error: 'Produto não encontrado' }),
          { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
        );
      }
      return new Response(
        JSON.stringify({ success: true, product }),
        { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Filtro por categoria
    if (category) {
      products = products.filter(p =>
        p.category === category ||
        p.categoryPath?.includes(category)
      );
    }

    // Filtro por estoque
    if (inStock === 'true') {
      products = products.filter(p => p.inStock === true);
    }

    // Formato Google Shopping XML
    if (format === 'google') {
      return generateGoogleFeed(products, data.storeInfo, siteUrl);
    }

    // Formato CSV para marketplaces
    if (format === 'csv') {
      return generateCSV(products);
    }

    // Formato JSON padrão
    return new Response(
      JSON.stringify({
        success: true,
        total: products.length,
        lastUpdated: data.lastUpdated,
        storeInfo: data.storeInfo,
        shipping: data.shipping,
        products,
        categories: data.categories
      }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (error) {
    console.error('Products API error:', error);
    return new Response(
      JSON.stringify({ success: false, error: error.message }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
}

/**
 * Gera feed XML para Google Shopping
 */
function generateGoogleFeed(products, storeInfo, siteUrl) {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <title>${storeInfo?.name || 'Blumenau Automação'}</title>
    <link>${siteUrl}</link>
    <description>Automação Industrial e Residencial em Blumenau</description>
${products.filter(p => p.inStock).map(p => `    <item>
      <g:id>${p.id}</g:id>
      <g:title><![CDATA[${p.name}]]></g:title>
      <g:description><![CDATA[${p.shortDescription || p.description?.substring(0, 500) || ''}]]></g:description>
      <g:link>${siteUrl}/produto.html?id=${p.id}</g:link>
      <g:image_link>${p.image}</g:image_link>
      <g:availability>${p.inStock ? 'in_stock' : 'out_of_stock'}</g:availability>
      <g:price>${p.price.toFixed(2)} BRL</g:price>
      <g:brand><![CDATA[${p.brand || 'Genérico'}]]></g:brand>
      <g:condition>${p.condition || 'new'}</g:condition>
      <g:gtin>${p.gtin || ''}</g:gtin>
      <g:mpn>${p.sku}</g:mpn>
      <g:google_product_category>${p.googleCategory || 'Hardware'}</g:google_product_category>
      <g:product_type><![CDATA[${p.categoryPath?.join(' > ') || p.category}]]></g:product_type>
      <g:shipping>
        <g:country>BR</g:country>
        <g:service>PAC</g:service>
        <g:price>0 BRL</g:price>
      </g:shipping>
    </item>`).join('\n')}
  </channel>
</rss>`;

  return new Response(xml, {
    headers: {
      ...corsHeaders,
      'Content-Type': 'application/xml; charset=utf-8',
      'Cache-Control': 'public, max-age=3600'
    }
  });
}

/**
 * Gera CSV para Shopee/Mercado Livre/outros marketplaces
 */
function generateCSV(products) {
  const headers = [
    'id', 'sku', 'gtin', 'nome', 'descricao', 'preco', 'estoque',
    'marca', 'categoria', 'peso_kg', 'comprimento_cm', 'largura_cm', 'altura_cm',
    'imagem_principal', 'imagens_adicionais', 'url'
  ];

  const rows = products.map(p => [
    p.id,
    p.sku,
    p.gtin || '',
    `"${p.name.replace(/"/g, '""')}"`,
    `"${(p.shortDescription || '').replace(/"/g, '""')}"`,
    p.price.toFixed(2),
    p.stock || 0,
    p.brand || '',
    p.categoryPath?.join(' > ') || p.category,
    p.weight || 0.5,
    p.dimensions?.length || 20,
    p.dimensions?.width || 15,
    p.dimensions?.height || 10,
    p.image,
    (p.images || []).slice(1).join('|'),
    p.sourceUrl || ''
  ]);

  const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');

  return new Response(csv, {
    headers: {
      ...corsHeaders,
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="products.csv"',
      'Cache-Control': 'public, max-age=3600'
    }
  });
}

/**
 * Handler OPTIONS para CORS
 */
export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}
