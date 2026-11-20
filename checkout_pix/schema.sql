CREATE TABLE IF NOT EXISTS checkout_sessoes (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  email TEXT NOT NULL,
  referencia_externa TEXT NOT NULL UNIQUE,
  assinatura_mp TEXT UNIQUE,
  estado_assinatura TEXT NOT NULL DEFAULT 'pending',
  estado_pagamento TEXT NOT NULL DEFAULT 'pending',
  ultimo_pagamento TEXT,
  acesso_ate TIMESTAMPTZ,
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS checkout_pagamentos (
  id_mp TEXT PRIMARY KEY,
  sessao_id TEXT NOT NULL REFERENCES checkout_sessoes(id),
  estado TEXT NOT NULL,
  valor NUMERIC(12, 2) NOT NULL,
  moeda TEXT NOT NULL,
  pago_em TIMESTAMPTZ,
  atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS checkout_sessoes_email_idx
  ON checkout_sessoes (lower(email));

CREATE INDEX IF NOT EXISTS checkout_pagamentos_sessao_idx
  ON checkout_pagamentos (sessao_id, pago_em DESC);
