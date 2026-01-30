/**
 * Blumenau Automação - Checkout API
 * Cloudflare Pages Function
 *
 * Recebe carrinho do frontend, valida estoque, cria preferência no Mercado Pago
 */

// Configurações
const MP_API_URL = 'https://api.mercadopago.com';

/**
 * Gera UUID v4 para referência externa
 */
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Valida dados do cliente
 */
function validateCustomer(customer) {
  const errors = [];

  if (!customer?.name?.trim()) {
    errors.push('Nome é obrigatório');
  }

  if (!customer?.email?.trim()) {
    errors.push('Email é obrigatório');
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(customer.email)) {
    errors.push('Email inválido');
  }

  if (!customer?.phone?.trim()) {
    errors.push('Telefone é obrigatório');
  }

  return errors;
}

/**
 * Valida CPF (algoritmo completo)
 */
function validateCPF(cpf) {
  if (!cpf) return false;

  cpf = cpf.replace(/\D/g, '');
  if (cpf.length !== 11) return false;

  // Verifica CPFs inválidos conhecidos
  if (/^(\d)\1+$/.test(cpf)) return false;

  // Validação dos dígitos verificadores
  let sum = 0;
  for (let i = 0; i < 9; i++) {
    sum += parseInt(cpf[i]) * (10 - i);
  }
  let digit = 11 - (sum % 11);
  if (digit > 9) digit = 0;
  if (parseInt(cpf[9]) !== digit) return false;

  sum = 0;
  for (let i = 0; i < 10; i++) {
    sum += parseInt(cpf[i]) * (11 - i);
  }
  digit = 11 - (sum % 11);
  if (digit > 9) digit = 0;
  if (parseInt(cpf[10]) !== digit) return false;

  return true;
}

/**
 * Valida itens do carrinho contra o banco de dados
 */
async function validateCartItems(db, items) {
  const errors = [];
  const validatedItems = [];

  if (!items || !Array.isArray(items) || items.length === 0) {
    return { errors: ['Carrinho vazio'], validatedItems: [] };
  }

  for (const item of items) {
    if (!item.id || !item.quantity || item.quantity < 1) {
      errors.push(`Item inválido no carrinho`);
      continue;
    }

    // Busca produto no banco
    const product = await db
      .prepare('SELECT * FROM products WHERE id = ? AND in_stock = 1')
      .bind(item.id)
      .first();

    if (!product) {
      errors.push(`Produto "${item.name || item.id}" não disponível`);
      continue;
    }

    // Verifica estoque se disponível
    if (product.stock !== null && product.stock < item.quantity) {
      errors.push(
        `Estoque insuficiente para "${product.name}". Disponível: ${product.stock}`
      );
      continue;
    }

    validatedItems.push({
      ...item,
      // Usa preço do banco (segurança - não confiar no frontend)
      unit_price: product.price,
      product_name: product.name,
      product_sku: product.sku,
      product_image: product.image,
    });
  }

  return { errors, validatedItems };
}

/**
 * Cria preferência de pagamento no Mercado Pago
 */
async function createMercadoPagoPreference(
  accessToken,
  orderData,
  siteUrl,
  externalReference
) {
  const preference = {
    items: orderData.items.map((item) => ({
      id: item.id,
      title: item.product_name,
      description: `SKU: ${item.product_sku || item.id}`,
      picture_url: item.product_image,
      quantity: item.quantity,
      currency_id: 'BRL',
      unit_price: item.unit_price,
    })),
    payer: {
      name: orderData.customer.name.split(' ')[0],
      surname: orderData.customer.name.split(' ').slice(1).join(' ') || '',
      email: orderData.customer.email,
      phone: {
        area_code: orderData.customer.phone?.substring(0, 2) || '',
        number: orderData.customer.phone?.substring(2) || '',
      },
      identification: orderData.customer.cpf
        ? {
            type: 'CPF',
            number: orderData.customer.cpf.replace(/\D/g, ''),
          }
        : undefined,
    },
    back_urls: {
      success: `${siteUrl}/checkout-success.html?ref=${externalReference}`,
      failure: `${siteUrl}/checkout-failure.html?ref=${externalReference}`,
      pending: `${siteUrl}/checkout-pending.html?ref=${externalReference}`,
    },
    auto_return: 'approved',
    external_reference: externalReference,
    notification_url: `${siteUrl}/api/webhook`,
    statement_descriptor: 'BLUMENAU AUTO',
    payment_methods: {
      excluded_payment_types: [],
      installments: 12,
    },
    expires: true,
    expiration_date_from: new Date().toISOString(),
    expiration_date_to: new Date(
      Date.now() + 24 * 60 * 60 * 1000
    ).toISOString(), // 24h
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

  // CORS headers
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json',
  };

  try {
    // Verifica token do Mercado Pago
    if (!env.MERCADOPAGO_ACCESS_TOKEN) {
      throw new Error('Mercado Pago não configurado');
    }

    // Parse do body
    const body = await request.json();
    const { items, customer, shipping } = body;

    // Valida cliente
    const customerErrors = validateCustomer(customer);

    // Valida CPF se fornecido
    if (customer?.cpf && !validateCPF(customer.cpf)) {
      customerErrors.push('CPF inválido');
    }

    if (customerErrors.length > 0) {
      return new Response(
        JSON.stringify({
          success: false,
          errors: customerErrors,
        }),
        { status: 400, headers: corsHeaders }
      );
    }

    // Valida itens do carrinho
    const { errors: itemErrors, validatedItems } = await validateCartItems(
      env.DB,
      items
    );

    if (itemErrors.length > 0) {
      return new Response(
        JSON.stringify({
          success: false,
          errors: itemErrors,
        }),
        { status: 400, headers: corsHeaders }
      );
    }

    // Calcula totais
    const subtotal = validatedItems.reduce(
      (sum, item) => sum + item.unit_price * item.quantity,
      0
    );
    const shippingCost = shipping?.cost || 0;
    const total = subtotal + shippingCost;

    // Gera referência externa única
    const externalReference = generateUUID();

    // Cria ou atualiza cliente no banco
    let customerId = null;
    const existingCustomer = await env.DB.prepare(
      'SELECT id FROM customers WHERE email = ?'
    )
      .bind(customer.email.toLowerCase())
      .first();

    if (existingCustomer) {
      customerId = existingCustomer.id;
      await env.DB.prepare(
        `UPDATE customers SET
          name = ?, phone = ?, cpf = ?, updated_at = datetime('now')
        WHERE id = ?`
      )
        .bind(
          customer.name,
          customer.phone,
          customer.cpf?.replace(/\D/g, '') || null,
          customerId
        )
        .run();
    } else {
      const result = await env.DB.prepare(
        `INSERT INTO customers (email, name, phone, cpf)
        VALUES (?, ?, ?, ?)`
      )
        .bind(
          customer.email.toLowerCase(),
          customer.name,
          customer.phone,
          customer.cpf?.replace(/\D/g, '') || null
        )
        .run();
      customerId = result.meta.last_row_id;
    }

    // Cria pedido no banco
    const orderResult = await env.DB.prepare(
      `INSERT INTO orders (
        external_reference, customer_id,
        customer_name, customer_email, customer_phone, customer_cpf,
        shipping_street, shipping_number, shipping_complement,
        shipping_neighborhood, shipping_city, shipping_state, shipping_zip_code,
        subtotal, shipping_cost, total, status
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')`
    )
      .bind(
        externalReference,
        customerId,
        customer.name,
        customer.email.toLowerCase(),
        customer.phone,
        customer.cpf?.replace(/\D/g, '') || null,
        shipping?.street || null,
        shipping?.number || null,
        shipping?.complement || null,
        shipping?.neighborhood || null,
        shipping?.city || null,
        shipping?.state || null,
        shipping?.zip_code || null,
        subtotal,
        shippingCost,
        total
      )
      .run();

    const orderId = orderResult.meta.last_row_id;

    // Insere itens do pedido
    for (const item of validatedItems) {
      await env.DB.prepare(
        `INSERT INTO order_items (
          order_id, product_id, product_name, product_sku, product_image,
          quantity, unit_price, total_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      )
        .bind(
          orderId,
          item.id,
          item.product_name,
          item.product_sku,
          item.product_image,
          item.quantity,
          item.unit_price,
          item.unit_price * item.quantity
        )
        .run();
    }

    // Cria preferência no Mercado Pago
    const siteUrl = env.SITE_URL || 'https://blumenauautomacao.com.br';
    const mpPreference = await createMercadoPagoPreference(
      env.MERCADOPAGO_ACCESS_TOKEN,
      { items: validatedItems, customer },
      siteUrl,
      externalReference
    );

    // Atualiza pedido com ID da preferência
    await env.DB.prepare(
      `UPDATE orders SET mp_preference_id = ?, updated_at = datetime('now') WHERE id = ?`
    )
      .bind(mpPreference.id, orderId)
      .run();

    // Retorna URL de checkout
    return new Response(
      JSON.stringify({
        success: true,
        data: {
          order_id: orderId,
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
