/**
 * Blumenau Automação - Shipping API
 *
 * POST /api/shipping
 * Body: { cep: "89055510", items: [{ id: "123", quantity: 1 }] }
 *
 * Retorna opções de frete:
 * - Frete grátis para Blumenau e região (até 15km do CEP 89055-510)
 * - Frete Correios (SEDEX/PAC) buscado da Proesi
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// CEP de origem (Blumenau - Rua João Pessoa, 2750, Bloco B, Velha)
const ORIGIN_CEP = '89036256';

// CEPs de Blumenau e região com frete grátis (prefixos)
// 89000 a 89099 = Blumenau e região
const FREE_SHIPPING_PREFIXES = [
  '89010', '89011', '89012', '89013', '89014', '89015', '89016', '89017', '89018', '89019',
  '89020', '89021', '89022', '89023', '89024', '89025', '89026', '89027', '89028', '89029',
  '89030', '89031', '89032', '89033', '89034', '89035', '89036', '89037', '89038', '89039',
  '89040', '89041', '89042', '89043', '89044', '89045', '89046', '89047', '89048', '89049',
  '89050', '89051', '89052', '89053', '89054', '89055', '89056', '89057', '89058', '89059',
  '89060', '89061', '89062', '89063', '89064', '89065', '89066', '89067', '89068', '89069',
  // Gaspar (próximo)
  '89110', '89111', '89112', '89113', '89114', '89115', '89116', '89117', '89118', '89119',
  // Pomerode (próximo)
  '89107',
  // Indaial (próximo)
  '89130', '89131', '89132', '89133', '89134', '89135', '89136', '89137', '89138', '89139',
];

/**
 * Verifica se CEP tem frete grátis (Blumenau e região)
 */
function isFreeShippingZone(cep) {
  const cleanCep = cep.replace(/\D/g, '');
  const prefix = cleanCep.substring(0, 5);
  return FREE_SHIPPING_PREFIXES.includes(prefix);
}

/**
 * Busca frete da Proesi para um produto
 */
async function fetchProesiShipping(productSlug, cep) {
  try {
    // A Proesi usa um endpoint de frete que podemos consultar
    // Primeiro tentamos buscar a página do produto para extrair o frete
    const productUrl = `https://www.proesi.com.br/${productSlug}`;

    // Alternativa: usar a API de frete se disponível
    // A maioria dos sites Magazord usa este padrão
    const shippingUrl = `https://www.proesi.com.br/frete/calcular`;

    const response = await fetch(shippingUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': productUrl
      },
      body: new URLSearchParams({
        cep: cep.replace(/\D/g, ''),
        slug: productSlug,
        quantidade: '1'
      })
    });

    if (response.ok) {
      const data = await response.json();
      return data;
    }
  } catch (error) {
    console.error('Proesi shipping fetch error:', error);
  }

  return null;
}

/**
 * Calcula frete via API dos Correios (fallback)
 */
async function calculateCorreiosShipping(cep, weight, dimensions) {
  try {
    // Usando a API pública dos Correios (pode ter limitações)
    const services = [
      { code: '04014', name: 'SEDEX', days: 3 },
      { code: '04510', name: 'PAC', days: 8 }
    ];

    const results = [];

    for (const service of services) {
      // API Correios (formato simplificado)
      const url = new URL('http://ws.correios.com.br/calculador/CalcPrecoPrazo.aspx');
      url.searchParams.set('nCdEmpresa', '');
      url.searchParams.set('sDsSenha', '');
      url.searchParams.set('nCdServico', service.code);
      url.searchParams.set('sCepOrigem', ORIGIN_CEP);
      url.searchParams.set('sCepDestino', cep.replace(/\D/g, ''));
      url.searchParams.set('nVlPeso', weight.toString());
      url.searchParams.set('nCdFormato', '1'); // Caixa
      url.searchParams.set('nVlComprimento', dimensions.length.toString());
      url.searchParams.set('nVlAltura', dimensions.height.toString());
      url.searchParams.set('nVlLargura', dimensions.width.toString());
      url.searchParams.set('nVlDiametro', '0');
      url.searchParams.set('sCdMaoPropria', 'N');
      url.searchParams.set('nVlValorDeclarado', '0');
      url.searchParams.set('sCdAvisoRecebimento', 'N');
      url.searchParams.set('StrRetorno', 'xml');

      try {
        const response = await fetch(url.toString());
        const text = await response.text();

        // Parse simples do XML
        const valorMatch = text.match(/<Valor>([^<]+)<\/Valor>/);
        const prazoMatch = text.match(/<PrazoEntrega>([^<]+)<\/PrazoEntrega>/);

        if (valorMatch && prazoMatch) {
          results.push({
            service: service.name,
            price: parseFloat(valorMatch[1].replace(',', '.')),
            days: parseInt(prazoMatch[1]) + 1, // +1 dia de manuseio
            carrier: 'Correios'
          });
        }
      } catch (e) {
        // Fallback com valores estimados
        results.push({
          service: service.name,
          price: service.name === 'SEDEX' ? 35.00 : 25.00,
          days: service.days,
          carrier: 'Correios',
          estimated: true
        });
      }
    }

    return results;
  } catch (error) {
    console.error('Correios API error:', error);
    return null;
  }
}

/**
 * Handler POST - Calcula frete
 */
export async function onRequestPost(context) {
  const { request } = context;

  try {
    const body = await request.json();
    const { cep, items } = body;

    if (!cep) {
      return new Response(
        JSON.stringify({ success: false, error: 'CEP é obrigatório' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const cleanCep = cep.replace(/\D/g, '');
    if (cleanCep.length !== 8) {
      return new Response(
        JSON.stringify({ success: false, error: 'CEP inválido' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Busca produtos para calcular peso e dimensões
    const url = new URL(request.url);
    const siteUrl = url.origin;
    const productsResponse = await fetch(`${siteUrl}/products.json`);
    const productsData = await productsResponse.json();

    // Calcula peso total e maior dimensão
    let totalWeight = 0;
    let maxDimensions = { length: 20, width: 15, height: 10 };
    let subtotal = 0;

    for (const item of (items || [])) {
      const product = productsData.products.find(p => p.id === item.id);
      if (product) {
        totalWeight += (product.weight || 0.5) * (item.quantity || 1);
        subtotal += product.price * (item.quantity || 1);

        if (product.dimensions) {
          maxDimensions.length = Math.max(maxDimensions.length, product.dimensions.length || 20);
          maxDimensions.width = Math.max(maxDimensions.width, product.dimensions.width || 15);
          maxDimensions.height = Math.max(maxDimensions.height, product.dimensions.height || 10);
        }
      }
    }

    // Peso mínimo para Correios
    if (totalWeight < 0.3) totalWeight = 0.3;

    const shippingOptions = [];

    // Verifica frete grátis local
    if (isFreeShippingZone(cleanCep)) {
      shippingOptions.push({
        id: 'local',
        service: 'Entrega Local',
        carrier: 'Blumenau Automação',
        price: 0,
        priceFormatted: 'Grátis',
        days: 2,
        daysText: '1-2 dias úteis',
        description: 'Entrega grátis em Blumenau e região',
        isFree: true
      });
    }

    // Tenta buscar frete da Proesi
    if (items?.length > 0) {
      const firstProduct = productsData.products.find(p => p.id === items[0].id);
      if (firstProduct?.slug) {
        const proesiShipping = await fetchProesiShipping(firstProduct.slug, cleanCep);
        if (proesiShipping?.opcoes) {
          for (const opcao of proesiShipping.opcoes) {
            shippingOptions.push({
              id: `proesi_${opcao.servico}`.toLowerCase().replace(/\s/g, '_'),
              service: opcao.servico,
              carrier: 'Correios',
              price: opcao.valor,
              priceFormatted: `R$ ${opcao.valor.toFixed(2).replace('.', ',')}`,
              days: opcao.prazo,
              daysText: `${opcao.prazo} dias úteis`,
              source: 'proesi'
            });
          }
        }
      }
    }

    // Fallback: calcula via Correios se não conseguiu da Proesi
    if (shippingOptions.filter(o => o.carrier === 'Correios').length === 0) {
      const correiosOptions = await calculateCorreiosShipping(cleanCep, totalWeight, maxDimensions);
      if (correiosOptions) {
        for (const option of correiosOptions) {
          shippingOptions.push({
            id: `correios_${option.service}`.toLowerCase(),
            service: option.service,
            carrier: option.carrier,
            price: option.price,
            priceFormatted: `R$ ${option.price.toFixed(2).replace('.', ',')}`,
            days: option.days,
            daysText: `${option.days} dias úteis`,
            estimated: option.estimated || false
          });
        }
      }
    }

    // Ordena por preço
    shippingOptions.sort((a, b) => a.price - b.price);

    return new Response(
      JSON.stringify({
        success: true,
        cep: cleanCep,
        origin: ORIGIN_CEP,
        isFreeShippingZone: isFreeShippingZone(cleanCep),
        totalWeight,
        subtotal,
        options: shippingOptions
      }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (error) {
    console.error('Shipping API error:', error);
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
