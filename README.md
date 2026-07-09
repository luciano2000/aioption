# Deriv Spike-Fade Bot (fase 1 — conta demo)

Bot que codifica a estrategia do Luciano: espera o mercado fazer uma
"parede" (vela outlier, z-score alto) e aposta na direcao contraria
com contrato binario Rise/Fall.

## Arquivos

- `download_history.py` — baixa candles de 1m da Deriv (dados publicos, sem token)
- `backtest.py` — testa a estrategia em dados historicos, varre parametros
- `bot.py` — bot ao vivo, SOMENTE conta demo (recusa token de conta real)

## Setup na VPS (Ubuntu/Debian)

```bash
sudo apt install -y python3-pip
pip3 install websockets
```

## 1. Backtest

```bash
python3 download_history.py R_100 30   # baixa 30 dias
python3 backtest.py R_100_1m.csv 0.925 # payout liquido real ~92.5%
```

## 2. Bot em demo

1. Crie conta na Deriv e selecione a conta **Virtual** (demo, $10k ficticios)
2. Em app.deriv.com > Configuracoes > Token de API, crie token com escopos `read` + `trade`
3. Rode:

```bash
DERIV_TOKEN=seu_token SYMBOL=R_100 Z_THRESHOLD=3.5 EXPIRY_MIN=1 STAKE=1 python3 bot.py
```

Para manter rodando: `nohup ... &` ou uma unit do systemd.
Resultados ficam em `trades.sqlite` e no stdout.

## Resultados do backtest (jun-jul/2026, payout 92.5%)

Melhor configuracao nos dois indices: **z >= 3.5, expiracao 1 min**
- R_100 (30 dias): 75 trades, 64.0% de acerto, +$17.40 por $1/op
- R_75 (15 dias): 39 trades, 66.7% de acerto, +$11.05 por $1/op
- Combinado: 114 trades, ~65% (≈2.8 sigma acima do break-even de 51.9%)

## AVISOS IMPORTANTES

1. **114 trades e pouco.** Pode ser sorte de amostra + vies de selecao
   (testamos 40 combinacoes de parametros; a melhor sempre parece boa).
2. **O backtest entra exatamente no fechamento da vela.** Ao vivo, ha
   1-2s de atraso e o preco de entrada e o tick do momento da compra —
   em cima de um pico, isso tende a jogar CONTRA a estrategia. So o
   teste em demo revela se a vantagem sobrevive.
3. Indices sinteticos (R_100 etc.) sao gerados por RNG auditado da
   Deriv — teoricamente random walk puro, sem vantagem possivel no
   longo prazo. Se a demo confirmar lucro por semanas, desconfie e
   investigue antes de por dinheiro real.
4. Rode em demo por PELO MENOS 500+ trades antes de qualquer conclusao.
5. Nunca use martingale. Stops diarios ja vem configurados no bot.

## Fase 2 (se a demo validar): painel web / SaaS

- OAuth oficial da Deriv (usuario autoriza sem dar senha)
- Registre seu app em api.deriv.com — da direito a **markup** (comissao
  do desenvolvedor sobre contratos executados pelo seu app_id)
- Backend FastAPI + este motor de sinal; frontend React com toggle
- Atencao a regulacao (CVM) antes de vender assinaturas no Brasil
