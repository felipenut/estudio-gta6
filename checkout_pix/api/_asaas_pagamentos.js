const { asaas, dataVencimentoInicial, gerarChaveLicenca, hash, sql } = require("./_comum");

function lista(dados) {
  return Array.isArray(dados && dados.data) ? dados.data : [];
}

function pago(status) {
  return status === "RECEIVED" || status === "CONFIRMED";
}

function estornado(status) {
  return ["REFUNDED", "PARTIALLY_REFUNDED", "CHARGEBACK_REQUESTED", "RECEIVED_IN_CASH_UNDONE"].includes(status);
}

function dataIso(valor) {
  const data = String(valor || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(data) ? data : null;
}

function somarMeses(dataIsoBase, meses) {
  const [ano, mes, dia] = dataIsoBase.split("-").map(Number);
  const indice = ano * 12 + (mes - 1) + meses;
  const novoAno = Math.floor(indice / 12);
  const novoMes = indice % 12;
  const ultimoDia = new Date(Date.UTC(novoAno, novoMes + 1, 0)).getUTCDate();
  return `${novoAno}-${String(novoMes + 1).padStart(2, "0")}-${String(Math.min(dia, ultimoDia)).padStart(2, "0")}`;
}

function proximoVencimento(pagamento, meses) {
  const vencimento = dataIso(pagamento.dueDate) || dataVencimentoInicial();
  const dataPagamento = dataIso(pagamento.paymentDate)
    || dataIso(pagamento.clientPaymentDate)
    || dataIso(pagamento.confirmedDate);
  const base = dataPagamento && dataPagamento > vencimento ? dataPagamento : vencimento;
  return somarMeses(base, meses);
}

async function localizarAssinatura(id) {
  const dados = await asaas(`/subscriptions?externalReference=${encodeURIComponent(id)}&limit=10`);
  return lista(dados).find((item) => item.externalReference === id) || null;
}

async function garantirAssinatura(sessao, pagamento) {
  if (sessao.asaas_subscription_id) return String(sessao.asaas_subscription_id);
  if (!sessao.asaas_customer_id || ![1, 3].includes(Number(sessao.duracao_meses))) {
    throw new Error("Dados da recorrência incompletos.");
  }

  const consulta = sql();
  const trava = await consulta`
    UPDATE checkout_sessoes
    SET estado_assinatura = 'criando_renovacao', atualizado_em = now()
    WHERE id = ${sessao.id}
      AND asaas_subscription_id IS NULL
      AND (estado_assinatura <> 'criando_renovacao' OR atualizado_em < now() - interval '2 minutes')
    RETURNING id
  `;
  if (!trava.length) {
    const atuais = await consulta`
      SELECT asaas_subscription_id FROM checkout_sessoes WHERE id = ${sessao.id} LIMIT 1
    `;
    if (atuais[0] && atuais[0].asaas_subscription_id) return String(atuais[0].asaas_subscription_id);
    throw new Error("A renovação está sendo preparada.");
  }

  try {
    let assinatura = await localizarAssinatura(String(sessao.id));
    if (!assinatura) {
      const meses = Number(sessao.duracao_meses);
      assinatura = await asaas("/subscriptions", {
        method: "POST",
        body: JSON.stringify({
          customer: String(sessao.asaas_customer_id),
          billingType: "PIX",
          nextDueDate: proximoVencimento(pagamento, meses),
          value: Number(sessao.valor_centavos) / 100,
          cycle: meses === 1 ? "MONTHLY" : "QUARTERLY",
          description: `Estúdio GTA 6 Shorts — plano ${meses === 1 ? "mensal" : "trimestral"}`,
          externalReference: String(sessao.id),
        }),
      });
    }
    if (!assinatura || !assinatura.id) throw new Error("Criação da recorrência não retornou um identificador.");
    await consulta`
      UPDATE checkout_sessoes
      SET asaas_subscription_id = ${String(assinatura.id)},
          estado_assinatura = ${String(assinatura.status || "ACTIVE")},
          atualizado_em = now()
      WHERE id = ${sessao.id}
    `;
    return String(assinatura.id);
  } catch (erro) {
    try {
      await consulta`
        UPDATE checkout_sessoes
        SET estado_assinatura = 'aguardando_pagamento', atualizado_em = now()
        WHERE id = ${sessao.id} AND asaas_subscription_id IS NULL
      `;
    } catch { /* preserva a falha original */ }
    throw erro;
  }
}

async function cancelarAssinatura(id) {
  if (!id) return;
  try {
    await asaas(`/subscriptions/${encodeURIComponent(id)}`, { method: "DELETE" });
  } catch (erro) {
    if (erro && erro.status === 404) return;
    throw erro;
  }
}

async function registrarPagamento(pagamento) {
  if (!pagamento || !pagamento.id || (!pago(pagamento.status) && !estornado(pagamento.status))) return false;
  if (pagamento.billingType !== "PIX") return false;

  const consulta = sql();
  const referencia = pagamento.externalReference ? String(pagamento.externalReference) : null;
  const assinaturaId = pagamento.subscription ? String(pagamento.subscription) : null;
  const sessoes = await consulta`
    SELECT id, referencia_externa, asaas_subscription_id, asaas_customer_id, valor_centavos,
           duracao_meses, estado_assinatura
    FROM checkout_sessoes
    WHERE (${referencia}::text IS NOT NULL AND referencia_externa = ${referencia})
       OR (${assinaturaId}::text IS NOT NULL AND asaas_subscription_id = ${assinaturaId})
    LIMIT 1
  `;
  if (!sessoes.length) return false;

  const sessao = sessoes[0];
  const valor = Number(pagamento.value || 0);
  const assinaturaConfere = Boolean(assinaturaId && assinaturaId === sessao.asaas_subscription_id);
  const referenciaConfere = referencia === sessao.referencia_externa
    && (!assinaturaId || assinaturaConfere);
  const clienteConfere = Boolean(sessao.asaas_customer_id)
    && String(pagamento.customer || "") === String(sessao.asaas_customer_id);
  if ((!referenciaConfere && !assinaturaConfere)
      || !clienteConfere
      || Math.round(valor * 100) !== Number(sessao.valor_centavos)) return false;

  if (pago(pagamento.status) && !sessao.asaas_subscription_id && !assinaturaId) {
    await garantirAssinatura(sessao, pagamento);
  }

  const status = String(pagamento.status);
  const chaveLicenca = pago(status) ? gerarChaveLicenca(sessao.id) : null;
  const hashLicenca = chaveLicenca ? hash(chaveLicenca) : null;
  const pagoEm = pago(status)
    ? String(pagamento.paymentDate || pagamento.clientPaymentDate || new Date().toISOString())
    : null;
  const vencimento = dataIso(pagamento.dueDate) || dataVencimentoInicial();

  await consulta`
    INSERT INTO checkout_pagamentos_asaas
      (id_asaas, sessao_id, estado, valor, due_date, pago_em)
    VALUES
      (${String(pagamento.id)}, ${sessao.id}, ${status}, ${valor}, ${vencimento}, ${pagoEm}::timestamptz)
    ON CONFLICT (id_asaas) DO UPDATE
    SET estado = EXCLUDED.estado,
        valor = EXCLUDED.valor,
        due_date = EXCLUDED.due_date,
        pago_em = CASE
          WHEN EXCLUDED.estado IN ('RECEIVED', 'CONFIRMED')
            THEN COALESCE(checkout_pagamentos_asaas.pago_em, EXCLUDED.pago_em)
          WHEN EXCLUDED.estado IN ('REFUNDED', 'PARTIALLY_REFUNDED', 'CHARGEBACK_REQUESTED', 'RECEIVED_IN_CASH_UNDONE')
            THEN NULL
          ELSE checkout_pagamentos_asaas.pago_em
        END,
        atualizado_em = now()
  `;

  await consulta`
    UPDATE checkout_sessoes s
    SET estado_pagamento = CASE
          WHEN EXISTS (
            SELECT 1 FROM checkout_pagamentos_asaas p
            WHERE p.sessao_id = s.id AND p.estado IN ('RECEIVED', 'CONFIRMED') AND p.pago_em IS NOT NULL
          ) THEN 'received'
          WHEN EXISTS (
            SELECT 1 FROM checkout_pagamentos_asaas p
            WHERE p.sessao_id = s.id AND p.estado IN ('REFUNDED', 'PARTIALLY_REFUNDED', 'CHARGEBACK_REQUESTED', 'RECEIVED_IN_CASH_UNDONE')
          ) THEN 'refunded'
          ELSE 'pending'
        END,
        ultimo_pagamento = ${String(pagamento.id)},
        licenca_hash = CASE
          WHEN ${hashLicenca}::text IS NOT NULL THEN ${hashLicenca}
          ELSE s.licenca_hash
        END,
        pix_qr_base64 = CASE
          WHEN ${String(pagamento.id)} = s.asaas_payment_id AND ${estornado(status)} THEN NULL
          ELSE s.pix_qr_base64
        END,
        pix_copia_cola = CASE
          WHEN ${String(pagamento.id)} = s.asaas_payment_id AND ${estornado(status)} THEN NULL
          ELSE s.pix_copia_cola
        END,
        pix_expira_em = CASE
          WHEN ${String(pagamento.id)} = s.asaas_payment_id AND ${estornado(status)} THEN NULL
          ELSE s.pix_expira_em
        END,
        acesso_ate = (
          SELECT MAX(GREATEST(p.due_date::timestamptz, p.pago_em) + s.duracao_meses * interval '1 month')
          FROM checkout_pagamentos_asaas p
          WHERE p.sessao_id = s.id AND p.estado IN ('RECEIVED', 'CONFIRMED') AND p.pago_em IS NOT NULL
        ),
        atualizado_em = now()
    WHERE s.id = ${sessao.id}
  `;

  if (["REFUNDED", "CHARGEBACK_REQUESTED", "RECEIVED_IN_CASH_UNDONE"].includes(status)) {
    let assinaturaAtual = sessao.asaas_subscription_id;
    if (!assinaturaAtual) {
      const atuais = await consulta`SELECT asaas_subscription_id FROM checkout_sessoes WHERE id = ${sessao.id} LIMIT 1`;
      assinaturaAtual = atuais[0] && atuais[0].asaas_subscription_id;
    }
    if (assinaturaAtual) {
      await cancelarAssinatura(String(assinaturaAtual));
      await consulta`
        UPDATE checkout_sessoes
        SET estado_assinatura = 'cancelled', atualizado_em = now()
        WHERE id = ${sessao.id}
      `;
    }
  }
  return true;
}

async function obterPix(consulta, sessao) {
  let pagamentoId = sessao.asaas_payment_id;
  if (!pagamentoId) {
    const dados = await asaas(`/payments?externalReference=${encodeURIComponent(String(sessao.id))}&limit=100`);
    const pagamentos = lista(dados).filter((item) => item && item.id && item.billingType === "PIX");
    const pagamento = pagamentos.find((item) => ["PENDING", "OVERDUE"].includes(item.status))
      || pagamentos.find((item) => pago(item.status))
      || null;
    if (!pagamento) return null;
    pagamentoId = String(pagamento.id);
  }

  const pagamento = await asaas(`/payments/${encodeURIComponent(pagamentoId)}`);
  if (!pagamento || !pagamento.id) return null;
  if (pago(pagamento.status)) {
    await registrarPagamento(pagamento);
    return { pagamentoId: String(pagamento.id), pago: true };
  }
  if (!["PENDING", "OVERDUE"].includes(pagamento.status)) {
    return { pagamentoId: String(pagamento.id), pago: false };
  }

  const dadosPix = await asaas(`/payments/${encodeURIComponent(pagamento.id)}/pixQrCode`);
  const imagemBase64 = typeof dadosPix.encodedImage === "string" ? dadosPix.encodedImage : "";
  const copiaCola = typeof dadosPix.payload === "string" ? dadosPix.payload : "";
  if (!imagemBase64 || !copiaCola) return null;
  const expiracao = dadosPix.expirationDate || null;
  await consulta`
    UPDATE checkout_sessoes
    SET asaas_payment_id = ${String(pagamento.id)},
        pix_qr_base64 = ${imagemBase64},
        pix_copia_cola = ${copiaCola},
        pix_expira_em = ${expiracao}::timestamptz,
        atualizado_em = now()
    WHERE id = ${sessao.id}
  `;
  return {
    pagamentoId: String(pagamento.id),
    pago: false,
    qrBase64: imagemBase64,
    copiaCola,
    expiraEm: expiracao,
  };
}

module.exports = { garantirAssinatura, obterPix, pago, registrarPagamento };
