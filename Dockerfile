FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY cue ./cue
COPY scripts ./scripts
RUN pip install --no-cache-dir .
ENV PORT=8080
CMD ["sh", "-c", "uvicorn cue.main:app --host 0.0.0.0 --port ${PORT}"]
