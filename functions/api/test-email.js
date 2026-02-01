/**
 * Endpoint de teste para verificar Resend
 * Acesse: https://www.blumenauautomacao.com.br/api/test-email
 */

export async function onRequestGet(context) {
  const { env } = context;

  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
  };

  // Verifica se tem API key
  if (!env.RESEND_API_KEY) {
    return new Response(
      JSON.stringify({
        success: false,
        error: 'RESEND_API_KEY não configurado no Cloudflare Secrets'
      }),
      { status: 500, headers: corsHeaders }
    );
  }

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
        subject: '✅ Teste de Email - Blumenau Automação',
        html: `
          <h2>Teste de Email</h2>
          <p>Se você está vendo isso, o Resend está funcionando corretamente!</p>
          <p>Data/hora: ${new Date().toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })}</p>
        `,
      }),
    });

    const result = await response.json();

    if (!response.ok) {
      return new Response(
        JSON.stringify({
          success: false,
          error: 'Erro do Resend',
          details: result
        }),
        { status: 500, headers: corsHeaders }
      );
    }

    return new Response(
      JSON.stringify({
        success: true,
        message: 'Email enviado! Verifique sua caixa de entrada.',
        resend_response: result
      }),
      { headers: corsHeaders }
    );

  } catch (error) {
    return new Response(
      JSON.stringify({
        success: false,
        error: error.message
      }),
      { status: 500, headers: corsHeaders }
    );
  }
}
