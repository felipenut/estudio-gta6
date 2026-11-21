const { hash, metodo, responder, sql } = require("./_comum");

module.exports = async function handler(req, res) {
  if (!metodo(req, res, "POST")) return;
  const token = req.body && req.body.tokenSessao;
  if (typeof token !== "string" || token.length < 40 || token.length > 100) {
    responder(res, 400, { erro: "Sessão inválida." });
    return;
  }

  try {
    const consulta = sql();
    const linhas = await consulta`
      SELECT estado_assinatura, estado_pagamento, acesso_ate
      FROM checkout_sessoes
      WHERE token_hash = ${hash(token)}
      LIMIT 1
    `;
    if (!linhas.length) {
      responder(res, 404, { erro: "Não encontramos esta sessão de checkout." });
      return;
    }

    const sessao = linhas[0];
    const ativo = sessao.estado_pagamento === "approved"
      && sessao.acesso_ate
      && new Date(sessao.acesso_ate).getTime() > Date.now();
    responder(res, 200, {
      estado: ativo ? "ativo" : sessao.estado_assinatura === "cancelled" ? "cancelado" : "aguardando",
      pagamento: sessao.estado_pagamento,
      acessoAte: sessao.acesso_ate,
      verificacaoAutomatica: true,
    });
  } catch (erro) {
    console.error("Falha ao consultar estado do checkout.", erro && erro.code ? erro.code : "erro interno");
    responder(res, 503, { erro: "Não foi possível consultar agora. Tente novamente." });
  }
};
