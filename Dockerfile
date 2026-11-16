# Optional operator-provided public CA certificates; no TLS verification is disabled.
FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt VERSION ./
COPY studioos ./studioos
COPY agents ./agents
RUN --mount=type=secret,id=studioos_build_ca,mode=0444 \
    studioos_ca_option="" \
 && if [ -s /run/secrets/studioos_build_ca ]; then \
      export CURL_CA_BUNDLE=/run/secrets/studioos_build_ca PIP_CERT=/run/secrets/studioos_build_ca; \
      studioos_ca_option="-o Acquire::https::CaInfo=/run/secrets/studioos_build_ca"; \
    fi \
 && apt-get $studioos_ca_option update \
 && apt-get $studioos_ca_option install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get $studioos_ca_option update \
 && apt-get $studioos_ca_option install -y --no-install-recommends postgresql-client-16 tesseract-ocr poppler-utils \
 && apt-get purge -y gnupg curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && pg_dump --version | grep -q '(PostgreSQL) 16' \
 && pip install --no-cache-dir -r requirements.txt \
 && mkdir -p /app/data /app/backups

ENV TZ=Asia/Kolkata PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "studioos.main:app", "--host", "0.0.0.0", "--port", "8000"]
