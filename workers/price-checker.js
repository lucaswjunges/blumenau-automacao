/**
 * Cloudflare Worker: Price & Stock Checker
 *
 * Verifica preço e estoque em tempo real no site da Proesi
 * para garantir que os dados do carrinho estão atualizados.
 *
 * Deploy: npx wrangler deploy
 */

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
  'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
};

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

/**
 * Extrai preço de uma página de produto da Proesi
 */
function extractPrice(html) {
  // Tenta múltiplos seletores comuns para preço
  const patterns = [
    // Meta tag de preço
    /meta[^>]*itemprop=["']price["'][^>]*content=["']([0-9.,]+)["']/i,
    /meta[^>]*property=["']product:price:amount["'][^>]*content=["']([0-9.,]+)["']/i,
    // Elemento de preço com classe comum
    /class=["'][^"']*price[^"']*["'][^>]*>R?\$?\s*([0-9.,]+)/i,
    /class=["']valor-big["'][^>]*>R?\$?\s*([0-9.,]+)/i,
    // JSON-LD schema
    /"price"\s*:\s*"?([0-9.,]+)"?/i,
  ];

  for (const pattern of patterns) {
    const match = html.match(pattern);
    if (match) {
      // Converte formato brasileiro para número
      const priceStr = match[1].replace(/\./g, '').replace(',', '.');
      const price = parseFloat(priceStr);
      if (!isNaN(price) && price > 0) {
        return price;
      }
    }
  }
  return null;
}

/**
 * Extrai disponibilidade de estoque
 */
function extractStock(html) {
  const lowerHtml = html.toLowerCase();

  // Verifica indicadores de indisponibilidade
  if (lowerHtml.includes('indisponível') ||
      lowerHtml.includes('esgotado') ||
      lowerHtml.includes('out of stock') ||
      lowerHtml.includes('unavailable')) {
    return { inStock: false, quantity: 0 };
  }

  // Tenta extrair quantidade
  const qtyPatterns = [
    /(\d+)\s*(?:unidade|pç|peça|und|disponíve)/i,
    /estoque[:\s]*(\d+)/i,
    /disponível[:\s]*(\d+)/i,
  ];

  for (const pattern of qtyPatterns) {
    const match = html.match(pattern);
    if (match) {
      return { inStock: true, quantity: parseInt(match[1]) };
    }
  }

  // Se não encontrou indicador de indisponibilidade, assume disponível
  return { inStock: true, quantity: null };
}

/**
 * Verifica um produto no site de origem
 */
async function checkProduct(url) {
  try {
    const response = await fetch(url, {
      headers: HEADERS,
      cf: {
        cacheTtl: 60, // Cache por 1 minuto no edge
        cacheEverything: true,
      },
    });

    if (!response.ok) {
      return {
        success: false,
        error: `HTTP ${response.status}`,
        url,
      };
    }

    const html = await response.text();
    const price = extractPrice(html);
    const stock = extractStock(html);

    return {
      success: true,
      url,
      price,
      ...stock,
      checkedAt: new Date().toISOString(),
    };
  } catch (error) {
    return {
      success: false,
      error: error.message,
      url,
    };
  }
}

/**
 * Handler principal do Worker
 */
export default {
  async fetch(request, env, ctx) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);

    // Endpoint: GET /check?url=...
    if (url.pathname === '/check' && request.method === 'GET') {
      const productUrl = url.searchParams.get('url');

      if (!productUrl) {
        return new Response(JSON.stringify({ error: 'Missing url parameter' }), {
          status: 400,
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        });
      }

      // Validar que é uma URL da Proesi
      if (!productUrl.includes('proesi.com.br')) {
        return new Response(JSON.stringify({ error: 'Only proesi.com.br URLs are supported' }), {
          status: 400,
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        });
      }

      const result = await checkProduct(productUrl);

      return new Response(JSON.stringify(result), {
        headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
      });
    }

    // Endpoint: POST /check-batch (múltiplos produtos)
    if (url.pathname === '/check-batch' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { urls } = body;

        if (!Array.isArray(urls) || urls.length === 0) {
          return new Response(JSON.stringify({ error: 'Missing urls array' }), {
            status: 400,
            headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
          });
        }

        // Limitar a 10 produtos por request
        if (urls.length > 10) {
          return new Response(JSON.stringify({ error: 'Maximum 10 URLs per request' }), {
            status: 400,
            headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
          });
        }

        // Verificar todos em paralelo
        const results = await Promise.all(
          urls.filter(u => u.includes('proesi.com.br')).map(checkProduct)
        );

        return new Response(JSON.stringify({ results }), {
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        });
      } catch (error) {
        return new Response(JSON.stringify({ error: 'Invalid JSON body' }), {
          status: 400,
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        });
      }
    }

    // Health check
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({ status: 'ok', timestamp: new Date().toISOString() }), {
        headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
      });
    }

    // 404 para outras rotas
    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404,
      headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
    });
  },
};
