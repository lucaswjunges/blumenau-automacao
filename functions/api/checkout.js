/**
 * Blumenau Automação - Checkout API
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
 * Envia notificação de pedido por email via Resend
 */
async function sendOrderNotification(env, orderData, externalReference) {
  // Se não tiver API key do Resend, só loga
  if (!env.RESEND_API_KEY) {
    console.log('RESEND_API_KEY não configurado - notificação por email desativada');
    return;
  }

  const { items, customer, shipping } = orderData;

  // Normaliza CEP
  const cep = shipping?.cep || shipping?.zip_code || '';
  const shippingCost = shipping?.cost || shipping?.shippingOption?.price || 0;
  const shippingMethod = shipping?.method || shipping?.shippingOption?.service || '';

  const total = items.reduce((sum, item) => sum + (item.price * item.quantity), 0);

  const emailHtml = `
<h2>🛒 Novo Pedido - Blumenau Automação</h2>
<p><strong>Referência:</strong> ${externalReference}</p>

<h3>Cliente</h3>
<p>
<strong>Nome:</strong> ${customer.name}<br>
<strong>Email:</strong> ${customer.email}<br>
<strong>Telefone:</strong> ${customer.phone}<br>
${customer.cpf ? `<strong>CPF:</strong> ${customer.cpf}<br>` : ''}${customer.cnpj ? `<strong>CNPJ:</strong> ${customer.cnpj}<br>` : ''}
</p>

<h3>Endereço de Entrega</h3>
<p>
${shipping ? `
${shipping.street}, ${shipping.number}${shipping.complement ? ` - ${shipping.complement}` : ''}<br>
${shipping.neighborhood}<br>
${shipping.city} - ${shipping.state}<br>
CEP: ${cep}
` : 'Não informado'}
</p>

<h3>Produtos</h3>
<ul>
${items.map(item => `<li>${item.name} (${item.quantity}x) - R$ ${(item.price * item.quantity).toFixed(2)}</li>`).join('')}
</ul>

<p><strong>Frete:</strong> ${shippingCost > 0 ? `R$ ${shippingCost.toFixed(2)} (${shippingMethod})` : 'Grátis'}</p>
<p><strong>Total:</strong> R$ ${(total + shippingCost).toFixed(2)}</p>

<hr>
<p><em>Aguardando confirmação de pagamento pelo Mercado Pago.</em></p>
`;

  try {
    const response = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'Blumenau Automação <contato@blumenauautomacao.com.br>',
        to: ['lucasw.junges@hotmail.com'],
        subject: `🛒 Novo Pedido #${externalReference.substring(0, 8)} - ${customer.name}`,
        html: emailHtml,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      console.error('Erro ao enviar email:', error);
    } else {
      console.log('Email de notificação enviado com sucesso');
    }
  } catch (error) {
    console.error('Erro ao enviar notificação:', error);
  }
}

/**
 * Cria preferência de pagamento no Mercado Pago
 */
async function createMercadoPagoPreference(accessToken, orderData, siteUrl, externalReference) {
  const { items, customer, shipping } = orderData;

  // Normaliza o CEP (frontend pode enviar como zip_code ou cep)
  const cep = shipping?.cep || shipping?.zip_code || '';

  // Monta itens incluindo frete se houver
  const mpItems = items.map((item) => ({
    id: item.id,
    title: item.name,
    description: `Produto: ${item.name}`,
    picture_url: item.image,
    quantity: item.quantity,
    currency_id: 'BRL',
    unit_price: Number(item.price),
  }));

  // Adiciona frete como item se não for grátis
  const shippingCost = shipping?.cost || shipping?.shippingOption?.price || 0;
  const shippingMethod = shipping?.method || shipping?.shippingOption?.service || 'Frete';
  const shippingCarrier = shipping?.carrier || shipping?.shippingOption?.carrier || 'Correios';

  if (shippingCost > 0) {
    mpItems.push({
      id: 'frete',
      title: `Frete - ${shippingMethod}`,
      description: `Envio via ${shippingCarrier}`,
      quantity: 1,
      currency_id: 'BRL',
      unit_price: Number(shippingCost),
    });
  }

  const preference = {
    items: mpItems,
    payer: {
      name: customer.name.split(' ')[0],
      surname: customer.name.split(' ').slice(1).join(' ') || '',
      email: customer.email,
      phone: {
        area_code: customer.phone?.replace(/\D/g, '').substring(0, 2) || '',
        number: customer.phone?.replace(/\D/g, '').substring(2) || '',
      },
      identification: (customer.cpf || customer.cnpj) ? {
        type: customer.cnpj ? 'CNPJ' : 'CPF',
        number: (customer.cnpj || customer.cpf).replace(/\D/g, ''),
      } : undefined,
      address: shipping ? {
        zip_code: cep.replace(/\D/g, ''),
        street_name: shipping.street,
        street_number: parseInt(shipping.number) || 0,
      } : undefined,
    },
    shipments: shipping ? {
      receiver_address: {
        zip_code: cep.replace(/\D/g, ''),
        street_name: shipping.street,
        street_number: parseInt(shipping.number) || 0,
        floor: shipping.complement || '',
        apartment: '',
        city_name: shipping.city,
        state_name: shipping.state,
      },
    } : undefined,
    back_urls: {
      success: `${siteUrl}/checkout-success.html`,
      failure: `${siteUrl}/checkout-failure.html`,
      pending: `${siteUrl}/checkout-pending.html`,
    },
    auto_return: 'approved',
    external_reference: externalReference,
    statement_descriptor: 'BLUMENAU AUTO',
    notification_url: `${siteUrl}/api/webhook-mp`,
    payment_methods: {
      installments: 12,
    },
    metadata: {
      customer_name: customer.name,
      customer_email: customer.email,
      customer_phone: customer.phone,
      shipping_address: shipping ? `${shipping.street}, ${shipping.number} - ${shipping.neighborhood}, ${shipping.city}/${shipping.state} - CEP ${cep}` : null,
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
    const { items, customer, shipping } = body;

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

    // Envia notificação por email
    try {
      await sendOrderNotification(env, { items, customer, shipping }, externalReference);
    } catch (emailError) {
      console.error('Erro ao enviar email de notificação:', emailError);
    }

    // Cria preferência no Mercado Pago
    const siteUrl = env.SITE_URL || 'https://www.blumenauautomacao.com.br';
    const mpPreference = await createMercadoPagoPreference(
      env.MERCADOPAGO_ACCESS_TOKEN,
      { items, customer, shipping },
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
