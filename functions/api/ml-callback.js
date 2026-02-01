/**
 * Mercado Livre OAuth Callback
 * Recebe o código de autorização e troca por tokens
 */

const ML_TOKEN_URL = 'https://api.mercadolibre.com/oauth/token';

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const code = url.searchParams.get('code');
  const error = url.searchParams.get('error');
  const state = url.searchParams.get('state'); // code_verifier para PKCE

  // Credenciais do ML
  const CLIENT_ID = env.ML_CLIENT_ID || '683384146533245';
  const CLIENT_SECRET = env.ML_CLIENT_SECRET;
  const REDIRECT_URI = 'https://www.blumenauautomacao.com.br/api/ml-callback';
  const CODE_VERIFIER = state || env.ML_CODE_VERIFIER; // PKCE code_verifier

  // Se houver erro
  if (error) {
    return new Response(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Erro - Mercado Livre</title>
        <style>
          body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
          .error { background: #ffebee; border: 1px solid #f44336; padding: 20px; border-radius: 8px; }
          h1 { color: #d32f2f; }
        </style>
      </head>
      <body>
        <div class="error">
          <h1>❌ Erro na Autorização</h1>
          <p><strong>Erro:</strong> ${error}</p>
          <p><strong>Descrição:</strong> ${url.searchParams.get('error_description') || 'Sem descrição'}</p>
          <p><a href="/">Voltar ao site</a></p>
        </div>
      </body>
      </html>
    `, {
      status: 400,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });
  }

  // Se não houver código
  if (!code) {
    return new Response(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Erro - Mercado Livre</title>
        <style>
          body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
          .error { background: #ffebee; border: 1px solid #f44336; padding: 20px; border-radius: 8px; }
        </style>
      </head>
      <body>
        <div class="error">
          <h1>❌ Código não encontrado</h1>
          <p>O código de autorização não foi recebido.</p>
          <p><a href="/">Voltar ao site</a></p>
        </div>
      </body>
      </html>
    `, {
      status: 400,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });
  }

  // Verifica se tem o secret configurado
  if (!CLIENT_SECRET) {
    return new Response(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Configuração Pendente</title>
        <style>
          body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
          .warning { background: #fff3e0; border: 1px solid #ff9800; padding: 20px; border-radius: 8px; }
          code { background: #f5f5f5; padding: 2px 6px; border-radius: 4px; }
        </style>
      </head>
      <body>
        <div class="warning">
          <h1>⚠️ Configuração Pendente</h1>
          <p>O <code>ML_CLIENT_SECRET</code> não está configurado no Cloudflare.</p>
          <p><strong>Código recebido:</strong></p>
          <code style="display: block; padding: 10px; word-break: break-all;">${code}</code>
          <p style="margin-top: 20px;">Configure o secret no Cloudflare Pages e tente novamente.</p>
        </div>
      </body>
      </html>
    `, {
      status: 500,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });
  }

  try {
    // Troca código por tokens
    const tokenResponse = await fetch(ML_TOKEN_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: CLIENT_ID,
        client_secret: CLIENT_SECRET,
        code: code,
        redirect_uri: REDIRECT_URI,
        code_verifier: CODE_VERIFIER,
      }),
    });

    const tokens = await tokenResponse.json();

    if (!tokenResponse.ok) {
      return new Response(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Erro - Tokens</title>
          <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
            .error { background: #ffebee; border: 1px solid #f44336; padding: 20px; border-radius: 8px; }
            pre { background: #f5f5f5; padding: 10px; overflow: auto; }
          </style>
        </head>
        <body>
          <div class="error">
            <h1>❌ Erro ao obter tokens</h1>
            <pre>${JSON.stringify(tokens, null, 2)}</pre>
          </div>
        </body>
        </html>
      `, {
        status: 400,
        headers: { 'Content-Type': 'text/html; charset=utf-8' }
      });
    }

    // Sucesso! Mostra os tokens para o usuário configurar
    return new Response(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>✅ Autorizado - Mercado Livre</title>
        <style>
          body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
          .success { background: #e8f5e9; border: 1px solid #4caf50; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
          .tokens { background: white; border: 1px solid #ddd; padding: 20px; border-radius: 8px; }
          h1 { color: #2e7d32; }
          .token-box { background: #f5f5f5; padding: 10px; border-radius: 4px; margin: 10px 0; word-break: break-all; font-family: monospace; font-size: 12px; }
          .label { font-weight: bold; color: #333; margin-top: 15px; }
          .warning { background: #fff3e0; border: 1px solid #ff9800; padding: 15px; border-radius: 8px; margin-top: 20px; }
          .copy-btn { background: #1976d2; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; margin-left: 10px; }
        </style>
      </head>
      <body>
        <div class="success">
          <h1>✅ Autorização Completa!</h1>
          <p>Sua aplicação foi autorizada no Mercado Livre com sucesso.</p>
        </div>

        <div class="tokens">
          <h2>🔑 Seus Tokens</h2>

          <p class="label">Access Token:</p>
          <div class="token-box" id="access-token">${tokens.access_token}</div>

          <p class="label">Refresh Token:</p>
          <div class="token-box" id="refresh-token">${tokens.refresh_token}</div>

          <p class="label">User ID:</p>
          <div class="token-box">${tokens.user_id}</div>

          <p class="label">Expira em:</p>
          <div class="token-box">${tokens.expires_in} segundos (${Math.round(tokens.expires_in / 3600)} horas)</div>
        </div>

        <div class="warning">
          <h3>⚠️ Importante - Configure no Cloudflare:</h3>
          <p>Adicione estes <strong>Secrets</strong> no Cloudflare Pages:</p>
          <ul>
            <li><code>ML_ACCESS_TOKEN</code> = (copie o Access Token acima)</li>
            <li><code>ML_REFRESH_TOKEN</code> = (copie o Refresh Token acima)</li>
            <li><code>ML_USER_ID</code> = ${tokens.user_id}</li>
          </ul>
          <p>Ou guarde em local seguro para usar no script Python.</p>
        </div>

        <p style="margin-top: 30px; text-align: center;">
          <a href="/" style="color: #1976d2;">← Voltar ao site</a>
        </p>
      </body>
      </html>
    `, {
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });

  } catch (error) {
    return new Response(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Erro</title>
        <style>
          body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
          .error { background: #ffebee; border: 1px solid #f44336; padding: 20px; border-radius: 8px; }
        </style>
      </head>
      <body>
        <div class="error">
          <h1>❌ Erro</h1>
          <p>${error.message}</p>
        </div>
      </body>
      </html>
    `, {
      status: 500,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });
  }
}
