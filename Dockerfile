FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Jakarta

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium

COPY . .

RUN mkdir -p sessions screenshots logs

EXPOSE 8000

CMD ["python", "cli.py", "serve"]
