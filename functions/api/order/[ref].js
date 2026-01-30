/**
 * Blumenau Automação - Order Status API
 * Cloudflare Pages Function
 *
 * Consulta status de pedido por referência externa
 * GET /api/order/{external_reference}
 */

export async function onRequestGet(context) {
  const { params, env } = context;
  const externalRef = params.ref;

  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
  };

  try {
    if (!externalRef) {
      return new Response(
        JSON.stringify({ success: false, error: 'Referência não fornecida' }),
        { status: 400, headers: corsHeaders }
      );
    }

    // Busca pedido
    const order = await env.DB.prepare(
      `SELECT
        id, external_reference, status,
        customer_name, customer_email,
        subtotal, shipping_cost, total,
        mp_status, mp_payment_type,
        created_at, paid_at
      FROM orders
      WHERE external_reference = ?`
    )
      .bind(externalRef)
      .first();

    if (!order) {
      return new Response(
        JSON.stringify({ success: false, error: 'Pedido não encontrado' }),
        { status: 404, headers: corsHeaders }
      );
    }

    // Busca itens do pedido
    const items = await env.DB.prepare(
      `SELECT
        product_id, product_name, product_sku, product_image,
        quantity, unit_price, total_price
      FROM order_items
      WHERE order_id = ?`
    )
      .bind(order.id)
      .all();

    return new Response(
      JSON.stringify({
        success: true,
        data: {
          ...order,
          items: items.results || [],
        },
      }),
      { status: 200, headers: corsHeaders }
    );
  } catch (error) {
    console.error('Order query error:', error);
    return new Response(
      JSON.stringify({ success: false, error: 'Erro interno' }),
      { status: 500, headers: corsHeaders }
    );
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}
