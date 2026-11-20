const crypto = require("node:crypto");
const { neon } = require("@neondatabase/serverless");

let consultaSql;

function responder(res, status, dados) {
  res.status(status).setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(dados));
}

function metodo(req, res, esperado) {
  if (req.method === esperado) return true;
  res.setHeader("Allow", esperado);
  responder(res, 405, { erro: `Use ${esperado}.` });
  return false;
}

function paraCentavos(valorOriginal) {
  const valor = String(valorOriginal || "").trim().replace(",", ".");
  if (!/^\d{1,5}(\.\d{1,2})?$/.test(valor)) return null;
  const centavos = Math.round(Number(valor) * 100);
  return centavos > 0 ? centavos : null;
}

function precos() {
  return [
    { id: "mensal", titulo: "Mensal", meses: 1, valorCentavos: paraCentavos(process.env.PLANO_MENSAL_BRL) },
    { id: "trimestral", titulo: "Trimestral", meses: 3, valorCentavos: paraCentavos(process.env.PLANO_TRIMESTRAL_BRL) },
  ];
}

function obterPlano(id) {
  const plano = precos().find((item) => item.id === id);
  return plano && plano.valorCentavos ? plano : null;
}

function baseUrl() {
  try {
    const url = new URL(process.env.APP_URL || "");
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function configuracao() {
  const ambiente = process.env.MP_AMBIENTE || "teste";
  const token = process.env.MP_ACCESS_TOKEN || "";
  const planos = precos();
  const testeEmAmbienteSeguro = ambiente === "teste" && process.env.VERCEL_ENV !== "production";
  const tokenDeTeste = token.startsWith("TEST-")
    || (token.startsWith("APP_USR-") && process.env.MP_CONFIRMAR_TESTE === "SIM");
  const sandbox = testeEmAmbienteSeguro && tokenDeTeste;
  const producao = ambiente === "producao"
    && token.startsWith("APP_USR-")
    && process.env.MP_CONFIRMAR_PRODUCAO === "SIM";
  const pronto = Boolean(
    process.env.DATABASE_URL
    && process.env.MP_WEBHOOK_SECRET
    && planos.every((plano) => plano.valorCentavos)
    && baseUrl()
    && (sandbox || producao)
  );
  return {
    pronto,
    ambiente: sandbox ? "teste" : producao ? "producao" : "desligado",
    planos,
    valorCentavos: planos[0].valorCentavos,
    moeda: "BRL",
    frequencia: "variável",
    motivo: pronto ? "" : "O checkout ainda não foi configurado no servidor.",
  };
}

function sql() {
  if (!process.env.DATABASE_URL) throw new Error("Banco não configurado.");
  if (!consultaSql) consultaSql = neon(process.env.DATABASE_URL);
  return consultaSql;
}

function hash(texto) {
  return crypto.createHash("sha256").update(texto).digest("hex");
}

function compararAssinatura(req, idEvento) {
  const assinatura = req.headers["x-signature"];
  const requisicaoId = req.headers["x-request-id"];
  if (typeof assinatura !== "string" || typeof requisicaoId !== "string" || !idEvento) return false;

  const partes = Object.fromEntries(
    assinatura.split(",").map((parte) => {
      const i = parte.indexOf("=");
      return i < 0 ? ["", ""] : [parte.slice(0, i).trim(), parte.slice(i + 1).trim()];
    })
  );
  if (!partes.ts || !partes.v1 || !/^[a-f0-9]{64}$/i.test(partes.v1)) return false;

  const manifesto = `id:${String(idEvento).toLowerCase()};request-id:${requisicaoId};ts:${partes.ts};`;
  const esperado = crypto.createHmac("sha256", process.env.MP_WEBHOOK_SECRET)
    .update(manifesto)
    .digest();
  const recebido = Buffer.from(partes.v1, "hex");
  return recebido.length === esperado.length && crypto.timingSafeEqual(recebido, esperado);
}

async function mercadoPago(path, opcoes = {}) {
  const resposta = await fetch(`https://api.mercadopago.com${path}`, {
    ...opcoes,
    headers: {
      Authorization: `Bearer ${process.env.MP_ACCESS_TOKEN}`,
      "Content-Type": "application/json",
      ...(opcoes.headers || {}),
    },
    signal: AbortSignal.timeout(15000),
  });
  const texto = await resposta.text();
  let dados = {};
  try { dados = texto ? JSON.parse(texto) : {}; } catch { /* resposta sem JSON */ }
  if (!resposta.ok) {
    const erro = new Error("Falha na comunicação com o Mercado Pago.");
    erro.status = resposta.status;
    throw erro;
  }
  return dados;
}

function idNotificacao(req, corpo) {
  const url = new URL(req.url || "/", "https://checkout.invalid");
  return url.searchParams.get("data.id")
    || (req.query && (req.query["data.id"] || req.query.id))
    || (corpo && corpo.data && corpo.data.id)
    || null;
}

module.exports = {
  baseUrl,
  compararAssinatura,
  configuracao,
  hash,
  idNotificacao,
  mercadoPago,
  metodo,
  obterPlano,
  responder,
  sql,
};
