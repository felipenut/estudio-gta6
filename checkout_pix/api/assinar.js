const crypto = require("node:crypto");
const {
  baseUrl,
  configuracao,
  hash,
  mercadoPago,
  metodo,
  preco,
  responder,
  sql,
} = require("./_comum");

function emailValido(valor) {
  return typeof valor === "string"
    && valor.length <= 254
    && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(valor.trim());
}

module.exports = async function handler(req, res) {
  if (!metodo(req, res, "POST")) return;
  if (!configuracao().pronto) {
    responder(res, 503, { erro: "Checkout indisponível. Configure o servidor primeiro." });
    return;
  }

  const email = req.body && req.body.email;
  if (!emailValido(email)) {
    responder(res, 400, { erro: "Informe um e-mail válido." });
    return;
  }

  const id = crypto.randomUUID();
  const tokenSessao = crypto.randomBytes(32).toString("base64url");
  const valorCentavos = preco();
  const valor = valorCentavos / 100;
  const origem = baseUrl();
  const consulta = sql();

  try {
    await consulta`
      INSERT INTO checkout_sessoes (id, token_hash, email, referencia_externa)
      VALUES (${id}, ${hash(tokenSessao)}, ${email.trim().toLowerCase()}, ${id})
    `;

    const retorno = `${origem}/?retorno=mercado-pago`;
    const notificacao = `${origem}/api/webhook`;
    const assinatura = await mercadoPago("/preapproval", {
      method: "POST",
      headers: { "X-Idempotency-Key": id },
      body: JSON.stringify({
        reason: "Estúdio GTA 6 Shorts — assinatura mensal",
        external_reference: id,
        payer_email: email.trim().toLowerCase(),
        auto_recurring: {
          frequency: 1,
          frequency_type: "months",
          transaction_amount: valor,
          currency_id: "BRL",
        },
        back_url: retorno,
        notification_url: notificacao,
        status: "pending",
      }),
    });

    const destino = assinatura.sandbox_init_point || assinatura.init_point;
    let destinoUrl;
    try { destinoUrl = new URL(destino); } catch { destinoUrl = null; }
    if (!destinoUrl || !/(^|\.)mercadopago\.com(\.br)?$/.test(destinoUrl.hostname)) {
      throw new Error("O Mercado Pago não retornou um endereço de checkout válido.");
    }

    await consulta`
      UPDATE checkout_sessoes
      SET assinatura_mp = ${String(assinatura.id)},
          estado_assinatura = ${String(assinatura.status || "pending")},
          atualizado_em = now()
      WHERE id = ${id}
    `;

    responder(res, 201, {
      checkoutUrl: destinoUrl.toString(),
      tokenSessao,
    });
  } catch (erro) {
    try {
      await consulta`
        UPDATE checkout_sessoes
        SET estado_assinatura = 'erro', atualizado_em = now()
        WHERE id = ${id} AND assinatura_mp IS NULL
      `;
    } catch { /* não substitui o erro original */ }
    console.error("Não foi possível iniciar a assinatura.", erro && erro.status ? `HTTP ${erro.status}` : "erro interno");
    responder(res, 502, { erro: "Não foi possível iniciar o checkout. Tente novamente em instantes." });
  }
};
