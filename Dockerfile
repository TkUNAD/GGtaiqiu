# 微信云托管：端口须与控制台「服务端口」一致（默认 80）
FROM python:3.9-slim

# qrcode[pil] / Pillow 需要系统库
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libjpeg62-turbo zlib1g libfreetype6 \
        fonts-dejavu-core \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app
COPY . .

# 腾讯云内构建推荐镜像源（与官方 wxcloudrun-flask 一致）
RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.cloud.tencent.com \
    && pip install --no-cache-dir -r backend/requirements.txt

# 云托管健康检查默认访问 80；应用通过 PORT 环境变量监听
ENV HOST=0.0.0.0
ENV PORT=80
ENV WX_CLOUD_RUN=1

EXPOSE 80

CMD ["python", "backend/app.py"]
