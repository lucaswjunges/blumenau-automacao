/**
 * Blumenau Automação - Product Description API
 *
 * GET /api/product-description?url=https://www.proesi.com.br/...
 *
 * Busca a descrição completa do produto na Proesi, incluindo tabelas.
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

/**
 * Extrai a descrição do produto do HTML da Proesi
 */
function extractProductDescription(html) {
  let description = '';
  let specs = {};

  // 1. Tenta extrair do JSON-LD (dados estruturados para SEO)
  const jsonLdPattern = /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi;
  let jsonLdMatch;

  while ((jsonLdMatch = jsonLdPattern.exec(html)) !== null) {
    try {
      const jsonData = JSON.parse(jsonLdMatch[1]);
      if (jsonData['@type'] === 'Product' || (Array.isArray(jsonData) && jsonData.find(item => item['@type'] === 'Product'))) {
        const product = jsonData['@type'] === 'Product' ? jsonData : jsonData.find(item => item['@type'] === 'Product');
        if (product && product.description) {
          description = product.description;
        }
      }
    } catch (e) {
      // JSON inválido, continua tentando outros métodos
    }
  }

  // 2. Tenta extrair do __NEXT_DATA__ ou dados React embutidos
  const nextDataPattern = /<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/i;
  const nextDataMatch = nextDataPattern.exec(html);
  if (nextDataMatch) {
    try {
      const nextData = JSON.parse(nextDataMatch[1]);
      // Procura descrição em diferentes caminhos comuns
      const desc = nextData?.props?.pageProps?.product?.description ||
                   nextData?.props?.pageProps?.data?.description ||
                   nextData?.pageProps?.product?.description;
      if (desc) description = desc;
    } catch (e) {}
  }

  // 3. Tenta extrair de window.__INITIAL_STATE__ ou similar (Magazord/outros)
  const initialStatePattern = /window\.__(?:INITIAL_STATE__|PRELOADED_STATE__|DATA__)__?\s*=\s*({[\s\S]*?});?\s*<\/script>/i;
  const stateMatch = initialStatePattern.exec(html);
  if (stateMatch) {
    try {
      const state = JSON.parse(stateMatch[1]);
      const desc = state?.product?.description || state?.pageData?.product?.description;
      if (desc) description = desc;
    } catch (e) {}
  }

  // 4. Padrões de HTML para descrição
  if (!description) {
    const descPatterns = [
      /<div[^>]*class="[^"]*descricao[^"]*produto[^"]*"[^>]*>([\s\S]*?)<\/div>/gi,
      /<div[^>]*class="[^"]*product-description[^"]*"[^>]*>([\s\S]*?)<\/div>/gi,
      /<div[^>]*id="[^"]*descricao[^"]*"[^>]*>([\s\S]*?)<\/div>/gi,
      /<section[^>]*class="[^"]*descricao[^"]*"[^>]*>([\s\S]*?)<\/section>/gi,
      /<div[^>]*class="[^"]*aba-descricao[^"]*"[^>]*>([\s\S]*?)<\/div>/gi,
    ];

    for (const pattern of descPatterns) {
      const match = pattern.exec(html);
      if (match && match[1] && match[1].length > 100) {
        description = match[1];
        break;
      }
    }
  }

  // 5. Busca tabelas de especificações
  const tablePattern = /<table[^>]*>([\s\S]*?)<\/table>/gi;
  const tables = [];
  let tableMatch;

  while ((tableMatch = tablePattern.exec(html)) !== null) {
    tables.push(tableMatch[0]);
  }

  // Extrai specs de tabelas
  for (const table of tables) {
    const rowPattern = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    let rowMatch;

    while ((rowMatch = rowPattern.exec(table)) !== null) {
      const cellPattern = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
      const cells = [];
      let cellMatch;

      while ((cellMatch = cellPattern.exec(rowMatch[1])) !== null) {
        const text = cellMatch[1]
          .replace(/<[^>]+>/g, '')
          .replace(/&nbsp;/g, ' ')
          .trim();
        if (text) cells.push(text);
      }

      if (cells.length >= 2) {
        specs[cells[0]] = cells[1];
      }
    }
  }

  // Limpa a descrição
  description = description
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<!--[\s\S]*?-->/g, '');

  // Decodifica entidades HTML
  description = decodeHtmlEntities(description);

  // Decodifica specs também
  const decodedSpecs = {};
  for (const [key, value] of Object.entries(specs)) {
    decodedSpecs[decodeHtmlEntities(key)] = decodeHtmlEntities(value);
  }

  return {
    description: description.trim(),
    specs: decodedSpecs,
    tables,
    hasContent: description.length > 0 || Object.keys(decodedSpecs).length > 0
  };
}

/**
 * Decodifica entidades HTML comuns
 */
function decodeHtmlEntities(text) {
  if (!text) return text;

  const entities = {
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&#39;': "'",
    '&apos;': "'",
    '&nbsp;': ' ',
    '&aacute;': 'á', '&Aacute;': 'Á',
    '&eacute;': 'é', '&Eacute;': 'É',
    '&iacute;': 'í', '&Iacute;': 'Í',
    '&oacute;': 'ó', '&Oacute;': 'Ó',
    '&uacute;': 'ú', '&Uacute;': 'Ú',
    '&agrave;': 'à', '&Agrave;': 'À',
    '&egrave;': 'è', '&Egrave;': 'È',
    '&igrave;': 'ì', '&Igrave;': 'Ì',
    '&ograve;': 'ò', '&Ograve;': 'Ò',
    '&ugrave;': 'ù', '&Ugrave;': 'Ù',
    '&atilde;': 'ã', '&Atilde;': 'Ã',
    '&otilde;': 'õ', '&Otilde;': 'Õ',
    '&ntilde;': 'ñ', '&Ntilde;': 'Ñ',
    '&acirc;': 'â', '&Acirc;': 'Â',
    '&ecirc;': 'ê', '&Ecirc;': 'Ê',
    '&icirc;': 'î', '&Icirc;': 'Î',
    '&ocirc;': 'ô', '&Ocirc;': 'Ô',
    '&ucirc;': 'û', '&Ucirc;': 'Û',
    '&ccedil;': 'ç', '&Ccedil;': 'Ç',
    '&ldquo;': '\u201c', '&rdquo;': '\u201d',
    '&lsquo;': '\u2018', '&rsquo;': '\u2019',
    '&hellip;': '...',
    '&mdash;': '-', '&ndash;': '-',
    '&deg;': '°',
    '&micro;': 'u',
    '&Omega;': 'Ohm', '&omega;': 'ohm',
  };

  let result = text;
  for (const [entity, char] of Object.entries(entities)) {
    result = result.replace(new RegExp(entity, 'g'), char);
  }

  // Decodifica entidades numéricas
  result = result.replace(/&#(\d+);/g, (match, dec) => String.fromCharCode(dec));
  result = result.replace(/&#x([0-9a-fA-F]+);/g, (match, hex) => String.fromCharCode(parseInt(hex, 16)));

  return result;
}

/**
 * Handler GET - Busca descrição do produto
 */
export async function onRequestGet(context) {
  const { request } = context;
  const url = new URL(request.url);
  const productUrl = url.searchParams.get('url');

  if (!productUrl) {
    return new Response(
      JSON.stringify({ success: false, error: 'URL do produto é obrigatória' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // Valida que é uma URL da Proesi
  if (!productUrl.includes('proesi.com.br')) {
    return new Response(
      JSON.stringify({ success: false, error: 'Apenas URLs da Proesi são suportadas' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  try {
    // Busca a página do produto
    const response = await fetch(productUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
      }
    });

    if (!response.ok) {
      return new Response(
        JSON.stringify({ success: false, error: 'Não foi possível acessar o produto' }),
        { status: response.status, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const html = await response.text();
    const extracted = extractProductDescription(html);

    return new Response(
      JSON.stringify({
        success: true,
        url: productUrl,
        ...extracted
      }),
      {
        headers: {
          ...corsHeaders,
          'Content-Type': 'application/json',
          'Cache-Control': 'public, max-age=3600' // Cache por 1 hora
        }
      }
    );

  } catch (error) {
    console.error('Product description fetch error:', error);
    return new Response(
      JSON.stringify({ success: false, error: error.message }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
}

/**
 * Handler OPTIONS para CORS
 */
export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}
