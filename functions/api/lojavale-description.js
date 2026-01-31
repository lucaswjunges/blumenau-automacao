/**
 * Blumenau Automacao - Loja Vale Product Description API
 *
 * GET /api/lojavale-description?url=https://www.lojavale.com.br/...
 *
 * Busca a descricao completa do produto na Loja Vale.
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

/**
 * Converte HTML para texto limpo
 */
function htmlToText(html) {
  if (!html) return '';

  let text = html
    // Quebras de linha
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>\s*<p[^>]*>/gi, '\n\n')
    .replace(/<p[^>]*>/gi, '')
    .replace(/<\/p>/gi, '\n')
    // Negrito - mantém texto
    .replace(/<strong[^>]*>([^<]*)<\/strong>/gi, '$1')
    .replace(/<b[^>]*>([^<]*)<\/b>/gi, '$1')
    // Links - extrai apenas o texto
    .replace(/<a[^>]*>([^<]*)<\/a>/gi, '$1')
    // Remove outras tags
    .replace(/<[^>]+>/g, '')
    // Decodifica entidades HTML comuns
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    // Limpa espaços
    .replace(/ +/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return text;
}

/**
 * Extrai a descricao do produto do HTML da Loja Vale
 */
function extractProductDescription(html) {
  let description = '';
  let specs = {};
  let warranty = '';
  let boxContents = '';
  let datasheet = '';
  let characteristics = '';

  // 1. Extrai descricao da div descricao-produto
  const descPattern = /<div[^>]*id="descricao-produto"[^>]*>\s*<div[^>]*class="content"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/i;
  const descMatch = descPattern.exec(html);
  if (descMatch) {
    // Converte HTML para texto limpo
    description = htmlToText(descMatch[1]);
  }

  // 2. Extrai "O que vem na caixa" (pode ser id="o-que-vem-na-caixa" ou id="acompanha")
  const boxPattern1 = /<div[^>]*id="o-que-vem-na-caixa"[^>]*>\s*<div[^>]*class="content"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/i;
  const boxMatch1 = boxPattern1.exec(html);
  if (boxMatch1) {
    boxContents = htmlToText(boxMatch1[1]);
  }

  // Padrao 2: id="acompanha" (Loja Vale)
  if (!boxContents) {
    const boxPattern2 = /<div[^>]*id="acompanha"[^>]*>\s*<div[^>]*class="content"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/i;
    const boxMatch2 = boxPattern2.exec(html);
    if (boxMatch2) {
      // Extrai itens da lista
      const listPattern = /<li[^>]*>([\s\S]*?)<\/li>/gi;
      let listMatch;
      const items = [];
      while ((listMatch = listPattern.exec(boxMatch2[1])) !== null) {
        const item = listMatch[1].replace(/<[^>]+>/g, '').trim();
        if (item) items.push(item);
      }
      boxContents = items.length > 0 ? items.join('\n') : htmlToText(boxMatch2[1]);
    }
  }

  // 2.5. Extrai "Características" - varios padroes possiveis
  // Padrao 1: Magazord (Seel/LojaVale) usa <dl> com <dt>/<dd> para caracteristicas
  // Estrutura: <div id="caracteristicas">...<dl class="grupo-carac"><span><dt>Key</dt><dd>Value</dd></span>...</dl>...</div>
  const charDlPattern = /<div[^>]*id="caracteristicas"[^>]*>[\s\S]*?<dl[^>]*>([\s\S]*?)<\/dl>/i;
  const charDlMatch = charDlPattern.exec(html);

  if (charDlMatch) {
    const dlContent = charDlMatch[1];
    const charLines = [];

    // Extrai pares dt/dd
    // Estrutura: <span class="table ..."><dt>Key</dt><dd>Value</dd></span>
    const dtPattern = /<dt[^>]*>([\s\S]*?)<\/dt>\s*<dd[^>]*>([\s\S]*?)<\/dd>/gi;
    let dtMatch;

    while ((dtMatch = dtPattern.exec(dlContent)) !== null) {
      const key = dtMatch[1].replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
      const value = dtMatch[2].replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
      if (key && value) {
        charLines.push(`${key}: ${value}`);
      }
    }

    if (charLines.length > 0) {
      characteristics = charLines.join('\n');
    }
  }

  // Padrao 2: Fallback - div id="caracteristicas" com tabela tradicional
  if (!characteristics) {
    const charTablePattern = /<div[^>]*id="caracteristicas"[^>]*>[\s\S]*?<table[^>]*>([\s\S]*?)<\/table>/i;
    const charTableMatch = charTablePattern.exec(html);

    if (charTableMatch) {
      const rowPattern = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
      let rowMatch;
      const charLines = [];

      while ((rowMatch = rowPattern.exec(charTableMatch[1])) !== null) {
        const cellPattern = /<td[^>]*>([\s\S]*?)<\/td>/gi;
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
          charLines.push(`${cells[0]}: ${cells[1]}`);
        } else if (cells.length === 1) {
          charLines.push(cells[0]);
        }
      }

      if (charLines.length > 0) {
        characteristics = charLines.join('\n');
      }
    }
  }

  // Padrao 2: section com title="Características"
  if (!characteristics) {
    const charPattern2 = /<[^>]*title="Caracter[ií]sticas"[^>]*>([\s\S]*?)<\/(?:section|div)>/i;
    const charMatch2 = charPattern2.exec(html);
    if (charMatch2) {
      characteristics = htmlToText(charMatch2[1]);
    }
  }

  // Padrao 3: div com class contendo "caracteristicas"
  if (!characteristics) {
    const charPattern3 = /<div[^>]*class="[^"]*caracteristicas[^"]*"[^>]*>([\s\S]*?)<\/div>/i;
    const charMatch3 = charPattern3.exec(html);
    if (charMatch3) {
      characteristics = htmlToText(charMatch3[1]);
    }
  }

  // Padrao 4: titulo h2/h3 "Características" seguido de conteudo
  if (!characteristics) {
    const charPattern4 = /<h[23][^>]*>\s*Caracter[ií]sticas\s*<\/h[23]>\s*([\s\S]*?)(?=<h[23]|<\/section|<\/article|$)/i;
    const charMatch4 = charPattern4.exec(html);
    if (charMatch4) {
      characteristics = htmlToText(charMatch4[1]);
    }
  }

  // 3. Extrai Garantia
  const warrantyPattern = /<strong>Garantia:<\/strong>\s*([\s\S]*?)(?:<\/p>|<br|<\/div>)/i;
  const warrantyMatch = warrantyPattern.exec(html);
  if (warrantyMatch) {
    warranty = warrantyMatch[1]
      .replace(/<[^>]+>/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // 4. Extrai link do datasheet
  const datasheetPattern = /href="([^"]*(?:pdf|datasheet)[^"]*)"/i;
  const datasheetMatch = datasheetPattern.exec(html);
  if (datasheetMatch) {
    datasheet = datasheetMatch[1];
  }

  // 5. Extrai especificacoes de tabelas
  const tablePattern = /<table[^>]*>([\s\S]*?)<\/table>/gi;
  let tableMatch;
  const tables = [];

  while ((tableMatch = tablePattern.exec(html)) !== null) {
    tables.push(tableMatch[0]);

    // Extrai specs de cada tabela
    const rowPattern = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    let rowMatch;

    while ((rowMatch = rowPattern.exec(tableMatch[1])) !== null) {
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

  // 6. Extrai preco do og:price ou product:price:amount
  let price = null;
  const pricePattern = /<meta[^>]*property="(?:og:price|product:price:amount)"[^>]*content="([^"]+)"/i;
  const priceMatch = pricePattern.exec(html);
  if (priceMatch) {
    price = parseFloat(priceMatch[1]);
  }

  // 7. Extrai imagem do og:image
  let image = '';
  const imagePattern = /<meta[^>]*property="og:image"[^>]*content="([^"]+)"/i;
  const imageMatch = imagePattern.exec(html);
  if (imageMatch) {
    image = imageMatch[1];
  }

  // 8. Extrai videos (YouTube/Vimeo da Loja Vale/Magazord)
  const videos = [];
  const videoPattern = /<div[^>]*class="[^"]*video-mini[^"]*"[^>]*data-url-video="([^"]+)"[^>]*>/gi;
  let videoMatch;

  while ((videoMatch = videoPattern.exec(html)) !== null) {
    let videoUrl = videoMatch[1].trim();
    if (!videoUrl) continue;

    let platform = 'unknown';

    // Detecta e normaliza YouTube
    if (videoUrl.includes('youtube.com') || videoUrl.includes('youtu.be')) {
      platform = 'youtube';
      const ytMatch = videoUrl.match(/(?:youtube\.com\/(?:embed\/|watch\?v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
      if (ytMatch) {
        videoUrl = `https://www.youtube.com/embed/${ytMatch[1]}`;
      }
    }
    // Detecta e normaliza Vimeo
    else if (videoUrl.includes('vimeo.com')) {
      platform = 'vimeo';
      const vimeoMatch = videoUrl.match(/vimeo\.com\/(?:video\/)?(\d+)/);
      if (vimeoMatch) {
        videoUrl = `https://player.vimeo.com/video/${vimeoMatch[1]}`;
      }
    }

    // Evita duplicatas
    if (!videos.some(v => v.url === videoUrl)) {
      videos.push({ url: videoUrl, platform });
    }
  }

  return {
    description,
    descriptionHtml: description.length > 0,
    specs,
    tables,
    warranty,
    boxContents,
    characteristics,
    datasheet,
    price,
    image,
    videos,
    hasContent: description.length > 0 || Object.keys(specs).length > 0 || characteristics.length > 0 || videos.length > 0
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
    '&aacute;': 'a', '&Aacute;': 'A',
    '&eacute;': 'e', '&Eacute;': 'E',
    '&iacute;': 'i', '&Iacute;': 'I',
    '&oacute;': 'o', '&Oacute;': 'O',
    '&uacute;': 'u', '&Uacute;': 'U',
    '&agrave;': 'a', '&Agrave;': 'A',
    '&atilde;': 'a', '&Atilde;': 'A',
    '&otilde;': 'o', '&Otilde;': 'O',
    '&ccedil;': 'c', '&Ccedil;': 'C',
  };

  let result = text;
  for (const [entity, char] of Object.entries(entities)) {
    result = result.replace(new RegExp(entity, 'g'), char);
  }

  // Decodifica entidades numericas
  result = result.replace(/&#(\d+);/g, (match, dec) => String.fromCharCode(dec));
  result = result.replace(/&#x([0-9a-fA-F]+);/g, (match, hex) => String.fromCharCode(parseInt(hex, 16)));

  return result;
}

/**
 * Handler GET - Busca descricao do produto
 */
export async function onRequestGet(context) {
  const { request } = context;
  const url = new URL(request.url);
  const productUrl = url.searchParams.get('url');

  if (!productUrl) {
    return new Response(
      JSON.stringify({ success: false, error: 'URL do produto e obrigatoria' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // Valida que e uma URL da Loja Vale ou Seel (ambas usam Magazord)
  if (!productUrl.includes('lojavale.com.br') && !productUrl.includes('seeldistribuidora.com.br')) {
    return new Response(
      JSON.stringify({ success: false, error: 'Apenas URLs da Loja Vale ou Seel sao suportadas' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  try {
    // Busca a pagina do produto
    const response = await fetch(productUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
      }
    });

    if (!response.ok) {
      return new Response(
        JSON.stringify({ success: false, error: 'Nao foi possivel acessar o produto' }),
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
    console.error('Loja Vale description fetch error:', error);
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
