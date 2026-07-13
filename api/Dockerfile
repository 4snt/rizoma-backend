FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# psycopg[binary] e asyncpg vêm com wheel — nenhum compilador é necessário.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# O container roda `alembic upgrade head` antes do uvicorn (ver docker-compose.yml),
# então alembic.ini e as revisões precisam estar na imagem.
COPY alembic.ini .
COPY alembic/ ./alembic/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
