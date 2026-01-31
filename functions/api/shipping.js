/**
 * Blumenau Automação - Shipping API (Simplificado)
 * Frete grátis para Blumenau e região, valores fixos para outras regiões
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type': 'application/json',
};

// CEPs de Blumenau e região com frete grátis (890xx)
function isFreeShippingZone(cep) {
  const prefix = cep.substring(0, 3);
  // 890xx = Blumenau, 891xx = região próxima (Gaspar, Pomerode, Indaial)
  return prefix === '890' || prefix === '891';
}

// Calcula frete baseado na região
function calculateShippingOptions(cep) {
  const options = [];

  // Frete grátis para Blumenau e região
  if (isFreeShippingZone(cep)) {
    options.push({
      id: 'local',
      service: 'Entrega Local',
      carrier: 'Blumenau Automação',
      price: 0,
      priceFormatted: 'Grátis',
      days: 2,
      daysText: '1-2 dias úteis',
      isFree: true
    });
  }

  // SC (88xxx, 89xxx) - frete reduzido
  const state = cep.substring(0, 2);
  if (state === '88' || state === '89') {
    options.push({
      id: 'sedex_sc',
      service: 'SEDEX',
      carrier: 'Correios',
      price: 25.00,
      priceFormatted: 'R$ 25,00',
      days: 3,
      daysText: '2-3 dias úteis',
      isFree: false
    });
    options.push({
      id: 'pac_sc',
      service: 'PAC',
      carrier: 'Correios',
      price: 18.00,
      priceFormatted: 'R$ 18,00',
      days: 5,
      daysText: '4-5 dias úteis',
      isFree: false
    });
  } else {
    // Outras regiões
    options.push({
      id: 'sedex',
      service: 'SEDEX',
      carrier: 'Correios',
      price: 45.00,
      priceFormatted: 'R$ 45,00',
      days: 5,
      daysText: '3-5 dias úteis',
      isFree: false
    });
    options.push({
      id: 'pac',
      service: 'PAC',
      carrier: 'Correios',
      price: 32.00,
      priceFormatted: 'R$ 32,00',
      days: 10,
      daysText: '7-10 dias úteis',
      isFree: false
    });
  }

  return options;
}

export async function onRequestPost(context) {
  try {
    const body = await context.request.json();
    const { cep } = body;

    if (!cep) {
      return new Response(
        JSON.stringify({ success: false, error: 'CEP é obrigatório' }),
        { status: 400, headers: corsHeaders }
      );
    }

    const cleanCep = cep.replace(/\D/g, '');
    if (cleanCep.length !== 8) {
      return new Response(
        JSON.stringify({ success: false, error: 'CEP inválido' }),
        { status: 400, headers: corsHeaders }
      );
    }

    const options = calculateShippingOptions(cleanCep);

    return new Response(
      JSON.stringify({
        success: true,
        cep: cleanCep,
        isFreeShippingZone: isFreeShippingZone(cleanCep),
        options
      }),
      { headers: corsHeaders }
    );

  } catch (error) {
    return new Response(
      JSON.stringify({ success: false, error: error.message }),
      { status: 500, headers: corsHeaders }
    );
  }
}

export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}
