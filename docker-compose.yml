services:
  deriv-bot:
    build: .
    restart: unless-stopped
    environment:
      DERIV_TOKEN: ${DERIV_TOKEN}   # token da conta VIRTUAL (demo)
      DERIV_APP_ID: "1089"
      SYMBOL: R_100
      Z_THRESHOLD: "3.5"
      EXPIRY_MIN: "1"
      STAKE: "1.0"
      STOP_LOSS_DAY: "20.0"
      STOP_WIN_DAY: "50.0"
    volumes:
      - deriv_data:/data
volumes:
  deriv_data:
