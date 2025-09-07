FROM python:3.11-slim

WORKDIR /app

COPY . .

ENV POETRY_VERSION=1.8.3
ENV POETRY_VIRTUALENVS_CREATE=false

RUN pip3 install poetry==$POETRY_VERSION

RUN poetry install --no-dev --no-interaction --verbose

EXPOSE 8000

ENTRYPOINT ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
