# Deploy no EasyPanel

## Opcao A — Compose (mais simples)
1. No EasyPanel: **+ Service > Compose**
2. Suba este zip descompactado pro servidor (ou use um repo Git) e aponte
   o compose para a pasta, OU cole o conteudo de `docker-compose.yml`
3. Em **Environment**, defina `DERIV_TOKEN` com o token da conta
   **Virtual** da Deriv (app.deriv.com > Configuracoes > Token de API,
   escopos read + trade)
4. Deploy. O bot recusa token de conta real por seguranca.

## Opcao B — App com Dockerfile
1. **+ Service > App** > Source: Git (suba esta pasta pro GitHub) ou upload
2. Build: Dockerfile (detectado automatico)
3. Environment (aba Env):
   - DERIV_TOKEN=seu_token_virtual   (obrigatorio)
   - SYMBOL=R_100
   - Z_THRESHOLD=3.5
   - EXPIRY_MIN=1
   - STAKE=1.0
4. Mounts: volume em `/data` (guarda o trades.sqlite entre deploys)
5. Deploy

## Acompanhar
- Logs em tempo real: aba **Logs** do servico (cada WIN/LOSS aparece la)
- Historico: `sqlite3 /data/trades.sqlite "SELECT status, COUNT(*), SUM(profit) FROM trades GROUP BY status;"`
  (via aba Console do servico)

Sem porta exposta — e um worker, nao precisa de dominio.
Meta: 500+ trades em demo antes de qualquer conclusao.
