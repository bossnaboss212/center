FROM python:3.11-slim

# Paquets système nécessaires (certificats SSL + build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Code du bot
COPY jefflebot_fr.py /app/jefflebot_fr.py

# Logs non bufferisés
ENV PYTHONUNBUFFERED=1

# Lancement
CMD ["python", "jefflebot_fr.py"]
