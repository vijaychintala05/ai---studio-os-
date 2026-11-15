# StudioOS image, used by both the app and the backup service. The version is set by STUDIOOS_VERSION.
# Pinned to Debian 12 (bookworm) so the PostgreSQL client source below matches.
FROM python:3.12-slim-bookworm

# PostgreSQL 16 client tools from the official PostgreSQL apt repository.
# The Debian default is version 15, which cannot back up a PostgreSQL 16 server.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 tesseract-ocr poppler-utils \
 && apt-get purge -y gnupg curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && pg_dump --version | grep -q '(PostgreSQL) 16'

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY VERSION ./VERSION
COPY studioos ./studioos
COPY agents ./agents
RUN mkdir -p /app/data /app/backups
ENV TZ=Asia/Kolkata PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "studioos.main:app", "--host", "0.0.0.0", "--port", "8000"]
