/**
 * Blumenau Automação - Checkout API (Simplificado)
 * Cloudflare Pages Function
 */

const MP_API_URL = 'https://api.mercadopago.com';

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Cria preferência de pagamento no Mercado Pago
 */
async function createMercadoPagoPreference(accessToken, orderData, siteUrl, externalReference) {
  const preference = {
    items: orderData.items.map((item) => ({
      id: item.id,
      title: item.name,
      description: `Produto: ${item.name}`,
      picture_url: item.image,
      quantity: item.quantity,
      currency_id: 'BRL',
      unit_price: Number(item.price),
    })),
    payer: {
      name: orderData.customer.name.split(' ')[0],
      surname: orderData.customer.name.split(' ').slice(1).join(' ') || '',
      email: orderData.customer.email,
      phone: {
        area_code: orderData.customer.phone?.replace(/\D/g, '').substring(0, 2) || '',
        number: orderData.customer.phone?.replace(/\D/g, '').substring(2) || '',
      },
    },
    back_urls: {
      success: `${siteUrl}/checkout-success.html`,
      failure: `${siteUrl}/checkout-failure.html`,
      pending: `${siteUrl}/checkout-pending.html`,
    },
    auto_return: 'approved',
    external_reference: externalReference,
    statement_descriptor: 'BLUMENAU AUTO',
    payment_methods: {
      installments: 12,
    },
  };

  const response = await fetch(`${MP_API_URL}/checkout/preferences`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(preference),
  });

  if (!response.ok) {
    const error = await response.json();
    console.error('Mercado Pago error:', error);
    throw new Error(error.message || 'Erro ao criar preferência de pagamento');
  }

  return response.json();
}

/**
 * Handler principal do checkout
 */
export async function onRequestPost(context) {
  const { request, env } = context;

  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json',
  };

  try {
    // Verifica token do Mercado Pago
    if (!env.MERCADOPAGO_ACCESS_TOKEN) {
      throw new Error('Mercado Pago não configurado. Configure MERCADOPAGO_ACCESS_TOKEN nas variáveis de ambiente.');
    }

    const body = await request.json();
    const { items, customer } = body;

    // Validação básica
    if (!items || items.length === 0) {
      return new Response(
        JSON.stringify({ success: false, errors: ['Carrinho vazio'] }),
        { status: 400, headers: corsHeaders }
      );
    }

    if (!customer?.name || !customer?.email || !customer?.phone) {
      return new Response(
        JSON.stringify({ success: false, errors: ['Preencha nome, email e telefone'] }),
        { status: 400, headers: corsHeaders }
      );
    }

    // Gera referência única
    const externalReference = generateUUID();

    // Cria preferência no Mercado Pago
    const siteUrl = env.SITE_URL || 'https://www.blumenauautomacao.com.br';
    const mpPreference = await createMercadoPagoPreference(
      env.MERCADOPAGO_ACCESS_TOKEN,
      { items, customer },
      siteUrl,
      externalReference
    );

    // Retorna URL de checkout
    return new Response(
      JSON.stringify({
        success: true,
        data: {
          external_reference: externalReference,
          init_point: mpPreference.init_point,
          sandbox_init_point: mpPreference.sandbox_init_point,
        },
      }),
      { status: 200, headers: corsHeaders }
    );
  } catch (error) {
    console.error('Checkout error:', error);

    return new Response(
      JSON.stringify({
        success: false,
        errors: [error.message || 'Erro interno no servidor'],
      }),
      { status: 500, headers: corsHeaders }
    );
  }
}

/**
 * Handler OPTIONS para CORS
 */
export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}
