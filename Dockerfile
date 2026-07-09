FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir websockets
COPY bot.py backtest.py download_history.py ./
ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/data/trades.sqlite
VOLUME /data
CMD ["python3", "bot.py"]
