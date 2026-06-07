# 1. Use the official uv image for a faster, smaller build
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 2. Set the working directory
WORKDIR /app

# 3. Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# 4. Copy only dependency files first (better caching)
COPY pyproject.toml uv.lock ./

# 5. Install dependencies without the project itself
# This layer stays cached unless your pyproject.toml changes
RUN uv sync --frozen --no-install-project

# 6. Copy the rest of your application code
COPY . .

# 7. Final sync after copying the source. The app runs from /app directly,
# so we do not install the project as a package.
RUN uv sync --frozen --no-install-project


ENV PATH="/app/.venv/bin:$PATH"
# 8. Set environment variables for production
ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# 9. Run the ASGI app through the virtualenv Python
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
