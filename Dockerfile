# ── Multi-stage build for chen-ai ──

FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir python-dotenv>=1.0.0

# Copy source
COPY *.py .
COPY *.json .
COPY examples/ examples/
COPY skills_data/ skills_data/
COPY mcp_data/ mcp_data/

# ── Runtime stage ──
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /app .

# Create data directories
RUN mkdir -p /app/memory_data /app/cache_data /app/telemetry

# Expose Gradio default port
EXPOSE 7860

# Default command: start Web UI
CMD ["python", "web_ui.py", "--server-name", "0.0.0.0"]

# To run CLI mode instead:
# docker run -it --rm -e OPENAI_API_KEY=sk-xxx ghcr.io/futao-augenstern/chen-ai python main.py