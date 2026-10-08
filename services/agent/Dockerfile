FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml
COPY agent_service ./agent_service

EXPOSE 8000
CMD ["uvicorn", "agent_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
