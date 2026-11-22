const { hash, metodo, responder, sql } = require("./_comum");

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function chaveCanonica(valor) {
  const limpa = String(valor || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!/^GTA6[0-9A-F]{32}$/.test(limpa)) return null;
  return `GTA6-${limpa.slice(4).match(/.{1,4}/g).join("-")}`;
}

module.exports = async function handler(req, res) {
  if (!metodo(req, res, "POST")) return;
  if (!process.env.DATABASE_URL || (process.env.LICENCA_SEGREDO || "").length < 32) {
    responder(res, 503, { erro: "Ativação de licença indisponível." });
    return;
  }

  const corpo = req.body && typeof req.body === "object" ? req.body : {};
  const acao = corpo.acao === "validar" ? "validar" : "ativar";
  const chave = chaveCanonica(corpo.chave);
  const dispositivo = typeof corpo.dispositivo === "string" ? corpo.dispositivo : "";
  if (!chave || !UUID.test(dispositivo)) {
    responder(res, 400, { erro: "Informe uma licença e um dispositivo válidos." });
    return;
  }

  try {
    const consulta = sql();
    let linhas = await consulta`
      SELECT id, estado_pagamento, acesso_ate, dispositivo_hash
      FROM checkout_sessoes
      WHERE licenca_hash = ${hash(chave)}
      LIMIT 1
    `;
    if (!linhas.length) {
      responder(res, 404, { erro: "Licença não encontrada. Confira o código informado." });
      return;
    }

    let licenca = linhas[0];
    const paga = ["received", "confirmed", "approved"].includes(String(licenca.estado_pagamento).toLowerCase());
    const vigente = licenca.acesso_ate && new Date(licenca.acesso_ate).getTime() > Date.now();
    if (!paga || !vigente) {
      responder(res, 403, { erro: "Esta licença não tem um período ativo. Confira o pagamento ou a renovação." });
      return;
    }

    const hashDispositivo = hash(dispositivo.toLowerCase());
    if (!licenca.dispositivo_hash && acao === "ativar") {
      await consulta`
        UPDATE checkout_sessoes
        SET dispositivo_hash = ${hashDispositivo},
            licenca_ativada_em = COALESCE(licenca_ativada_em, now()),
            atualizado_em = now()
        WHERE id = ${licenca.id} AND dispositivo_hash IS NULL
      `;
      linhas = await consulta`
        SELECT id, estado_pagamento, acesso_ate, dispositivo_hash
        FROM checkout_sessoes WHERE id = ${licenca.id} LIMIT 1
      `;
      licenca = linhas[0] || licenca;
    }

    if (licenca.dispositivo_hash !== hashDispositivo) {
      responder(res, 409, { erro: "Esta licença já está ativada em outro computador." });
      return;
    }
    responder(res, 200, { ativo: true, acessoAte: licenca.acesso_ate });
  } catch (erro) {
    console.error("Falha ao validar licença.", "erro interno");
    responder(res, 503, { erro: "Não foi possível validar a licença agora. Tente novamente." });
  }
};
