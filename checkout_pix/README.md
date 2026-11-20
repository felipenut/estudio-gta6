# Checkout do Estúdio GTA 6 Shorts

Serviço separado do programa Windows: página pública, criação de assinatura mensal no Mercado Pago, webhook assinado e registro persistente em Neon. O projeto é preparado para ser publicado na Vercel com o diretório `checkout_pix` como raiz.

## O que já faz

- Recebe o e-mail do comprador e define o preço exclusivamente no servidor.
- Cria assinatura mensal pendente no Mercado Pago e encaminha o comprador à tela hospedada pelo provedor.
- Mantém o token privado no servidor, valida a assinatura HMAC dos webhooks e consulta o recurso no Mercado Pago antes de atualizar o estado.
- Só marca acesso como ativo quando encontra uma cobrança aprovada em BRL. Reenvios de aviso não duplicam o período pago.
- Mantém o checkout desativado até as variáveis obrigatórias estarem corretas.

O Mercado Pago mostra os meios de pagamento habilitados para a conta durante o checkout. Esta página não gera nem simula um QR Pix próprio.

## Preparação

1. Crie um projeto no Neon e execute `schema.sql` no SQL Editor.
2. Importe o repositório na Vercel e defina `checkout_pix` como **Root Directory**.
3. Conecte as variáveis do Neon e adicione as variáveis abaixo nos ambientes **Development** e **Preview**:

   - `DATABASE_URL`: conexão Neon com SSL.
   - `APP_URL`: endereço HTTPS do checkout, sem barra no final.
   - `MP_AMBIENTE`: `teste`.
   - `MP_ACCESS_TOKEN`: Access Token de teste com prefixo `TEST-`.
   - `MP_WEBHOOK_SECRET`: segredo de assinatura de Webhooks da aplicação Mercado Pago.
   - `PLANO_MENSAL_BRL`: preço mensal em reais, por exemplo `29.90`.

4. Publique um Preview e faça uma compra com os usuários de teste do Mercado Pago. A confirmação via webhook exige uma URL HTTPS pública. A API envia `APP_URL/api/webhook` em `notification_url` ao criar a assinatura e trata os eventos `subscription_preapproval`, `subscription_authorized_payment` e `payment`.

O endpoint retorna HTTP 503 e a página não aceita compra se faltar uma configuração ou se o ambiente não corresponder ao prefixo do token.

## Produção

O padrão é teste e o token `APP_USR-` é recusado nesse modo. Para ligar produção somente depois de validar o Preview, configure `MP_AMBIENTE=producao`, `MP_ACCESS_TOKEN` de produção, `MP_CONFIRMAR_PRODUCAO=SIM`, segredo de webhook de produção, URL de produção e preço aprovado. Use os escopos de ambiente da Vercel para não misturar credenciais.

## Limite desta etapa

Esta entrega registra o estado da assinatura e o período pago. A ativação/limite por computador dentro do aplicativo Windows ainda precisa ser conectada a um endereço fixo de produção; não se deve bloquear instalações atuais antes de publicar e validar o serviço. O checkout também não dispara e-mail de licença.

## Rotas

- `GET /api/config`: configuração pública do checkout, sem credenciais.
- `POST /api/assinar`: recebe `{ "email": "..." }` e devolve a URL do Mercado Pago e um token de sessão aleatório.
- `POST /api/status`: recebe `{ "tokenSessao": "..." }` e devolve apenas o estado daquela sessão.
- `POST /api/webhook`: valida HMAC e consulta o pagamento/assinatura pela API do Mercado Pago.
