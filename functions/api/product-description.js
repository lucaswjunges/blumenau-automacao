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
  let tables = [];

  // 1. PRIMEIRO: Busca tabelas de especificações na div de descrição
  // Proesi usa #descricao-produto > .content com tabelas
  // Regex simplificada - apenas encontra o conteúdo entre <div class="content"> e </div></div>
  const descStartPattern = /<div[^>]*id="descricao-produto"[^>]*>\s*<div[^>]*class="content"[^>]*>/i;
  const descStartMatch = descStartPattern.exec(html);

  if (descStartMatch) {
    // Encontra onde começa o conteúdo
    const contentStart = descStartMatch.index + descStartMatch[0].length;
    // Encontra onde termina (</div></div> do descricao-produto)
    const endPattern = /<\/div>\s*<\/div>\s*<div[^>]*(?:class="[^"]*caracteristicas|id="caracteristicas")/i;
    const endMatch = endPattern.exec(html.substring(contentStart));
    const contentEnd = endMatch ? contentStart + endMatch.index : html.indexOf('</div></div>', contentStart);
    const contentHtml = html.substring(contentStart, contentEnd);

    // Extrai tabelas do conteúdo
    const tablePattern = /<table[^>]*>([\s\S]*?)<\/table>/gi;
    let tableMatch;
    while ((tableMatch = tablePattern.exec(contentHtml)) !== null) {
      tables.push(tableMatch[0]);

      // Extrai specs de cada tabela
      const rowPattern = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
      let rowMatch;
      while ((rowMatch = rowPattern.exec(tableMatch[0])) !== null) {
        const cellPattern = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
        const cells = [];
        let cellMatch;
        while ((cellMatch = cellPattern.exec(rowMatch[1])) !== null) {
          const text = cellMatch[1]
            .replace(/<[^>]+>/g, '')
            .replace(/&nbsp;/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
          if (text) cells.push(text);
        }
        if (cells.length >= 2) {
          specs[cells[0]] = cells[1];
        }
      }
    }

    // Extrai descrição SEM as tabelas
    let descText = contentHtml
      .replace(/<table[\s\S]*?<\/table>/gi, '')  // Remove tabelas
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '') // Remove iframes (YouTube etc)
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<style[\s\S]*?<\/style>/gi, '')
      .replace(/<!--[\s\S]*?-->/g, '');

    // Remove seção de "Dados Técnicos" / "Especificações" se já extraímos tabela
    if (tables.length > 0) {
      // Remove heading de dados técnicos e tudo que vem depois (incluindo variações de acentuação)
      descText = descText.replace(/<h[1-6][^>]*>[^<]*(?:Dados\s*T[eé]cnicos|Especifica[çc][oõ]es)[^<]*<\/h[1-6]>[\s\S]*/gi, '');
    }

    // Converte paragrafos e headings para texto formatado
    descText = descText
      .replace(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/gi, '\n\n$1\n\n')
      .replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '$1\n\n')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, '• $1\n')
      .replace(/<[^>]+>/g, '')  // Remove outras tags
      .replace(/&nbsp;/g, ' ')
      .replace(/\n{3,}/g, '\n\n')  // Max 2 newlines
      .trim();

    // Remove "Dados Técnicos" do texto final também (caso tenha vazado do HTML para o texto)
    if (tables.length > 0) {
      // Remove qualquer texto que contenha "Dados Técnicos" ou "Especificações" e tudo depois
      descText = descText.replace(/[^.!?]*(?:Dados\s*T[eé]cnicos|Especifica[çc][oõ]es\s*T[eé]cnicas?)[\s\S]*/gi, '').trim();

      // Limpa final - remove frases de call-to-action (usando regex não-gulosa)
      descText = descText.replace(/\.?\s*Confira[^.]*?(?:a\s*baixo|abaixo)\.?\s*$/gi, '.').trim();
      descText = descText.replace(/\.?\s*Veja[^.]*?(?:a\s*baixo|abaixo)\.?\s*$/gi, '.').trim();
      // Remove trailing punctuation, hifens e espaços
      descText = descText.replace(/\s*[-–:.]\s*$/g, '').trim();
    }

    description = decodeHtmlEntities(descText);
  }

  // 2. Se não encontrou na div, tenta JSON-LD (fallback, menos preferido)
  if (!description) {
    const jsonLdPattern = /<script[^>]*type="application\/ld\+json"[^>]*id="product-schema"[^>]*>([\s\S]*?)<\/script>/i;
    const jsonLdMatch = jsonLdPattern.exec(html);

    if (jsonLdMatch) {
      try {
        const jsonData = JSON.parse(jsonLdMatch[1]);
        if (jsonData['@type'] === 'Product' && jsonData.description) {
          // Remove a parte de "Dados Técnicos" se tiver tabela
          let desc = jsonData.description;
          if (tables.length > 0) {
            // Corta antes de "Dados Técnicos" ou similar
            desc = desc.replace(/\s*(Alicate Amperímetro [^-]+-\s*)?Dados Técnicos[\s\S]*/i, '');
            desc = desc.replace(/\s*Especificações Técnicas[\s\S]*/i, '');
          }
          description = desc.trim();
        }
      } catch (e) {
        // JSON inválido
      }
    }
  }

  // 3. Se ainda não tem descrição, tenta padrões genéricos de HTML
  if (!description) {
    const descPatterns = [
      /<div[^>]*class="[^"]*descricao[^"]*produto[^"]*"[^>]*>([\s\S]*?)<\/div>/gi,
      /<div[^>]*class="[^"]*product-description[^"]*"[^>]*>([\s\S]*?)<\/div>/gi,
      /<section[^>]*class="[^"]*descricao[^"]*"[^>]*>([\s\S]*?)<\/section>/gi,
    ];

    for (const pattern of descPatterns) {
      const match = pattern.exec(html);
      if (match && match[1] && match[1].length > 100) {
        description = match[1]
          .replace(/<table[\s\S]*?<\/table>/gi, '')
          .replace(/<[^>]+>/g, '')
          .replace(/&nbsp;/g, ' ')
          .trim();
        description = decodeHtmlEntities(description);
        break;
      }
    }
  }

  // 4. Se não encontrou tabelas na descrição, busca em todo o documento
  if (tables.length === 0) {
    const globalTablePattern = /<table[^>]*>([\s\S]*?)<\/table>/gi;
    let tableMatch;
    while ((tableMatch = globalTablePattern.exec(html)) !== null) {
      // Ignora tabelas de navegação/layout (geralmente sem <td> com conteúdo útil)
      if (tableMatch[0].includes('<td') && tableMatch[0].length > 200) {
        tables.push(tableMatch[0]);

        // Extrai specs
        const rowPattern = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
        let rowMatch;
        while ((rowMatch = rowPattern.exec(tableMatch[0])) !== null) {
          const cellPattern = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
          const cells = [];
          let cellMatch;
          while ((cellMatch = cellPattern.exec(rowMatch[1])) !== null) {
            const text = cellMatch[1]
              .replace(/<[^>]+>/g, '')
              .replace(/&nbsp;/g, ' ')
              .replace(/\s+/g, ' ')
              .trim();
            if (text) cells.push(text);
          }
          if (cells.length >= 2) {
            specs[cells[0]] = cells[1];
          }
        }
      }
    }
  }

  // Decodifica specs
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
