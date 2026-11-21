CREATE TABLE IF NOT EXISTS checkout_sessoes (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  email TEXT NOT NULL,
  referencia_externa TEXT NOT NULL UNIQUE,
  plano TEXT NOT NULL DEFAULT 'mensal',
  valor_centavos INTEGER NOT NULL DEFAULT 2990,
  duracao_meses INTEGER NOT NULL DEFAULT 1,
  assinatura_mp TEXT UNIQUE,
  estado_assinatura TEXT NOT NULL DEFAULT 'pending',
  estado_pagamento TEXT NOT NULL DEFAULT 'pending',
  ultimo_pagamento TEXT,
  acesso_ate TIMESTAMPTZ,
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migração segura para bancos que já usavam o checkout mensal.
ALTER TABLE checkout_sessoes
  ADD COLUMN IF NOT EXISTS plano TEXT NOT NULL DEFAULT 'mensal';
ALTER TABLE checkout_sessoes
  ADD COLUMN IF NOT EXISTS valor_centavos INTEGER NOT NULL DEFAULT 2990;
ALTER TABLE checkout_sessoes
  ADD COLUMN IF NOT EXISTS duracao_meses INTEGER NOT NULL DEFAULT 1;

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
