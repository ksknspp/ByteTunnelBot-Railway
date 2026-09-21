FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       curl \
       jq \
       ca-certificates \
       ncurses-bin \
    && rm -rf /var/lib/apt/lists/*

# Compatibility for the Termux-specific "pkg install" inside bytetunnel.sh
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/pkg \
    && chmod +x /usr/local/bin/pkg

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
