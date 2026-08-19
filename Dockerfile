FROM python:3.12-slim

# Éviter les buffers stdout (logs immédiats)
ENV PYTHONUNBUFFERED=1

# Dépendances système minimales
RUN apt-get update && apt-get install -y \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
RUN pip install --no-cache-dir python-can

# Dossier de travail
WORKDIR /app

# Copier le programme
COPY can2yd.py /app/can2yd.py

# Valeurs par défaut (surchargeables)
ENV MODE=server
ENV CAN_IFACE=can0
ENV TCP_HOST=
ENV TCP_PORT=2223
ENV RECONNECT_DELAY=5

# Port TCP RAW ASCII YachtDevices
EXPOSE 2223

# Commande de lancement
CMD ["python", "/app/can2yd.py"]
