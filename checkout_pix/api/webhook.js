const {
  compararAssinatura,
  configuracao,
  idNotificacao,
  mercadoPago,
  metodo,
  responder,
  sql,
} = require("./_comum");

function tipoNotificacao(req, corpo) {
  const url = new URL(req.url || "/", "https://checkout.invalid");
  return url.searchParams.get("type")
    || url.searchParams.get("topic")
    || (req.query && (req.query.type || req.query.topic))
    || (corpo && (corpo.type || corpo.topic))
    || "";
}

async function registrarAssinatura(consulta, id) {
  const assinatura = await mercadoPago(`/preapproval/${encodeURIComponent(id)}`);
  if (!assinatura.external_reference) throw new Error("Assinatura sem referência da sessão.");
  const linhas = await consulta`
    UPDATE checkout_sessoes
    SET assinatura_mp = ${String(assinatura.id)},
        estado_assinatura = ${String(assinatura.status || "pending")},
        atualizado_em = now()
    WHERE referencia_externa = ${String(assinatura.external_reference)}
    RETURNING id
  `;
  if (!linhas.length) throw new Error("Sessão da assinatura ainda não encontrada.");
}

async function registrarPagamento(consulta, pagamento) {
  const idReferencia = pagamento.external_reference;
  const idAssinatura = pagamento.preapproval_id;
  if (!idReferencia && !idAssinatura) return;

  const sessoes = await consulta`
    SELECT id, estado_pagamento, acesso_ate, valor_centavos, duracao_meses
    FROM checkout_sessoes
    WHERE (${idReferencia || null}::text IS NOT NULL AND referencia_externa = ${idReferencia || null})
       OR (${idAssinatura || null}::text IS NOT NULL AND assinatura_mp = ${idAssinatura || null})
    LIMIT 1
  `;
  if (!sessoes.length) throw new Error("Sessão do pagamento ainda não encontrada.");

  const sessao = sessoes[0];
  const status = String(pagamento.status || "unknown");
  const valor = Number(pagamento.transaction_amount || 0);
  const moeda = String(pagamento.currency_id || "");
  const aprovado = status === "approved"
    && moeda === "BRL"
    && Math.round(valor * 100) === Number(sessao.valor_centavos);
  const pagoEm = pagamento.date_approved || pagamento.date_last_updated || new Date().toISOString();

  await consulta`
    INSERT INTO checkout_pagamentos (id_mp, sessao_id, estado, valor, moeda, pago_em)
    VALUES (${String(pagamento.id)}, ${sessao.id}, ${status}, ${valor}, ${moeda}, ${aprovado ? pagoEm : null})
    ON CONFLICT (id_mp) DO UPDATE
    SET estado = EXCLUDED.estado,
        valor = EXCLUDED.valor,
        moeda = EXCLUDED.moeda,
        pago_em = CASE
          WHEN EXCLUDED.estado = 'approved' THEN COALESCE(checkout_pagamentos.pago_em, EXCLUDED.pago_em)
          WHEN EXCLUDED.estado IN ('refunded', 'charged_back', 'cancelled') THEN NULL
          ELSE checkout_pagamentos.pago_em
        END,
        atualizado_em = now()
  `;

  if (aprovado) {
    await consulta`
      UPDATE checkout_sessoes
      SET estado_pagamento = 'approved',
          ultimo_pagamento = ${String(pagamento.id)},
          acesso_ate = GREATEST(COALESCE(acesso_ate, '-infinity'::timestamptz), ${pagoEm}::timestamptz + ${sessao.duracao_meses} * interval '1 month'),
          atualizado_em = now()
      WHERE id = ${sessao.id}
    `;
  } else if (["rejected", "cancelled", "refunded", "charged_back"].includes(status)) {
    await consulta`
      UPDATE checkout_sessoes
      SET estado_pagamento = CASE
            WHEN EXISTS (
              SELECT 1 FROM checkout_pagamentos
              WHERE sessao_id = ${sessao.id} AND estado = 'approved' AND pago_em IS NOT NULL
            ) THEN 'approved'
            ELSE ${status}
          END,
          acesso_ate = (
            SELECT MAX(pago_em) + ${sessao.duracao_meses} * interval '1 month'
            FROM checkout_pagamentos
            WHERE sessao_id = ${sessao.id} AND estado = 'approved' AND pago_em IS NOT NULL
          ),
          atualizado_em = now()
      WHERE id = ${sessao.id}
    `;
  }
}

module.exports = async function handler(req, res) {
  if (!metodo(req, res, "POST")) return;
  if (!configuracao().pronto) {
    responder(res, 503, { erro: "Webhook ainda não configurado." });
    return;
  }

  const corpo = req.body && typeof req.body === "object" ? req.body : {};
  const id = idNotificacao(req, corpo);
  if (!compararAssinatura(req, id)) {
    responder(res, 401, { erro: "Assinatura do aviso inválida." });
    return;
  }

  try {
    const consulta = sql();
    const tipo = tipoNotificacao(req, corpo);
    if (tipo === "subscription_preapproval") {
      await registrarAssinatura(consulta, id);
    } else if (tipo === "subscription_authorized_payment") {
      const fatura = await mercadoPago(`/authorized_payments/${encodeURIComponent(id)}`);
      if (fatura.payment && fatura.payment.id) {
        const pagamento = await mercadoPago(`/v1/payments/${encodeURIComponent(fatura.payment.id)}`);
        if (!pagamento.preapproval_id && fatura.preapproval_id) pagamento.preapproval_id = fatura.preapproval_id;
        if (!pagamento.external_reference && fatura.external_reference) pagamento.external_reference = fatura.external_reference;
        await registrarPagamento(consulta, pagamento);
      }
    } else if (tipo === "payment") {
      const pagamento = await mercadoPago(`/v1/payments/${encodeURIComponent(id)}`);
      await registrarPagamento(consulta, pagamento);
    }
    responder(res, 200, { recebido: true });
  } catch (erro) {
    console.error("Falha ao processar aviso do Mercado Pago.", erro && erro.status ? `HTTP ${erro.status}` : "erro interno");
    responder(res, 503, { erro: "Não foi possível processar o aviso agora." });
  }
};
