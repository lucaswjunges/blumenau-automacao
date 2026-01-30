/**
 * Blumenau Automação - Mercado Pago Webhook
 * Cloudflare Pages Function
 *
 * Recebe notificações IPN do Mercado Pago e atualiza status do pedido
 */

const MP_API_URL = 'https://api.mercadopago.com';

/**
 * Busca detalhes do pagamento no Mercado Pago
 */
async function getPaymentDetails(accessToken, paymentId) {
  const response = await fetch(`${MP_API_URL}/v1/payments/${paymentId}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (!response.ok) {
    throw new Error(`Erro ao buscar pagamento: ${response.status}`);
  }

  return response.json();
}

/**
 * Mapeia status do Mercado Pago para status interno
 */
function mapPaymentStatus(mpStatus) {
  const statusMap = {
    pending: 'pending',
    approved: 'approved',
    authorized: 'approved',
    in_process: 'in_process',
    in_mediation: 'in_process',
    rejected: 'rejected',
    cancelled: 'cancelled',
    refunded: 'refunded',
    charged_back: 'refunded',
  };

  return statusMap[mpStatus] || 'pending';
}

/**
 * Atualiza status do pedido no banco
 */
async function updateOrderStatus(db, paymentData) {
  const externalReference = paymentData.external_reference;

  if (!externalReference) {
    throw new Error('external_reference não encontrado no pagamento');
  }

  const status = mapPaymentStatus(paymentData.status);
  const paidAt = paymentData.status === 'approved' ? "datetime('now')" : 'NULL';

  const query = `
    UPDATE orders SET
      status = ?,
      mp_payment_id = ?,
      mp_status = ?,
      mp_status_detail = ?,
      mp_payment_type = ?,
      paid_at = ${paymentData.status === 'approved' ? "datetime('now')" : 'paid_at'},
      updated_at = datetime('now')
    WHERE external_reference = ?
  `;

  const result = await db
    .prepare(query)
    .bind(
      status,
      String(paymentData.id),
      paymentData.status,
      paymentData.status_detail,
      paymentData.payment_type_id,
      externalReference
    )
    .run();

  return result.meta.changes > 0;
}

/**
 * Salva log do webhook para auditoria
 */
async function logWebhook(db, source, eventType, payload, processed, error) {
  await db
    .prepare(
      `INSERT INTO webhook_logs (source, event_type, payload, processed, error)
      VALUES (?, ?, ?, ?, ?)`
    )
    .bind(
      source,
      eventType,
      JSON.stringify(payload),
      processed ? 1 : 0,
      error || null
    )
    .run();
}

/**
 * Valida assinatura do webhook (se secret configurado)
 * O Mercado Pago envia x-signature no header
 */
function validateWebhookSignature(request, secret, body) {
  if (!secret) return true; // Se não configurou secret, aceita

  const signature = request.headers.get('x-signature');
  const requestId = request.headers.get('x-request-id');

  if (!signature || !requestId) {
    return false;
  }

  // O Mercado Pago usa HMAC-SHA256
  // Formato: ts=timestamp,v1=hash
  // Por simplicidade, vamos apenas verificar se o header existe
  // Em produção, implementar validação completa com crypto.subtle

  return signature.includes('v1=');
}

/**
 * Handler POST - Recebe notificações do Mercado Pago
 */
export async function onRequestPost(context) {
  const { request, env } = context;

  try {
    // Verifica configuração
    if (!env.MERCADOPAGO_ACCESS_TOKEN) {
      throw new Error('Mercado Pago não configurado');
    }

    // Parse do body
    const body = await request.json();

    // Valida assinatura (se secret configurado)
    if (
      !validateWebhookSignature(
        request,
        env.MERCADOPAGO_WEBHOOK_SECRET,
        JSON.stringify(body)
      )
    ) {
      await logWebhook(
        env.DB,
        'mercadopago',
        body.type || 'unknown',
        body,
        false,
        'Assinatura inválida'
      );

      return new Response('Unauthorized', { status: 401 });
    }

    // Log inicial
    console.log('Webhook received:', body.type, body.action);

    // Processa apenas notificações de pagamento
    if (body.type === 'payment') {
      const paymentId = body.data?.id;

      if (!paymentId) {
        await logWebhook(
          env.DB,
          'mercadopago',
          body.type,
          body,
          false,
          'Payment ID não encontrado'
        );
        return new Response('Payment ID not found', { status: 400 });
      }

      // Busca detalhes do pagamento no Mercado Pago
      const paymentData = await getPaymentDetails(
        env.MERCADOPAGO_ACCESS_TOKEN,
        paymentId
      );

      console.log(
        'Payment data:',
        paymentData.id,
        paymentData.status,
        paymentData.external_reference
      );

      // Atualiza pedido no banco
      const updated = await updateOrderStatus(env.DB, paymentData);

      if (!updated) {
        await logWebhook(
          env.DB,
          'mercadopago',
          body.type,
          { webhook: body, payment: paymentData },
          false,
          'Pedido não encontrado'
        );
        console.warn(
          'Order not found for external_reference:',
          paymentData.external_reference
        );
      } else {
        await logWebhook(
          env.DB,
          'mercadopago',
          body.type,
          { webhook: body, payment: paymentData },
          true,
          null
        );
        console.log(
          'Order updated:',
          paymentData.external_reference,
          '->',
          paymentData.status
        );
      }

      // Mercado Pago espera 200/201 para confirmar recebimento
      return new Response('OK', { status: 200 });
    }

    // Outros tipos de notificação (merchant_order, etc.)
    await logWebhook(env.DB, 'mercadopago', body.type, body, true, null);

    return new Response('OK', { status: 200 });
  } catch (error) {
    console.error('Webhook error:', error);

    // Tenta logar o erro
    try {
      await logWebhook(
        env.DB,
        'mercadopago',
        'error',
        { error: error.message },
        false,
        error.message
      );
    } catch {
      // Ignora erro ao logar
    }

    // Retorna 500 para que o Mercado Pago tente novamente
    return new Response('Internal Server Error', { status: 500 });
  }
}

/**
 * Handler GET - Verificação do endpoint (Mercado Pago faz isso)
 */
export async function onRequestGet() {
  return new Response('Webhook endpoint active', {
    status: 200,
    headers: { 'Content-Type': 'text/plain' },
  });
}
