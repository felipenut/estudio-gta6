const { configuracao, metodo, responder } = require("./_comum");

module.exports = function handler(req, res) {
  if (!metodo(req, res, "GET")) return;
  responder(res, 200, configuracao());
};
