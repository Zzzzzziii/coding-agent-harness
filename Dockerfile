FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY harness ./harness
COPY config.yaml ./
COPY prompts ./prompts
RUN pip install --no-cache-dir .
EXPOSE 8000
USER 65532
CMD ["python", "-m", "harness", "serve"]
