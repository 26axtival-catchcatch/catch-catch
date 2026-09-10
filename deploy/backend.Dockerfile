FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_SYNC=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock /app/backend/
RUN uv sync --frozen --no-dev --no-install-project --project backend
COPY backend/src /app/backend/src
RUN uv sync --frozen --no-dev --project backend
COPY data/seeding/hackathon-2week/onboarded-sources /app/seed-sources
COPY deploy/backend-entrypoint.sh /app/backend-entrypoint.sh
# Git checkouts can inherit a restrictive umask on SSM. Public build inputs
# must remain readable by the non-root runtime account. No env files are copied.
RUN chmod -R a+rX /app/backend/src /app/seed-sources \
    && chmod a+r /app/backend/pyproject.toml /app/backend/uv.lock /app/backend-entrypoint.sh
RUN useradd --uid 10001 --create-home app && mkdir -p /app/data && chown app:app /app/data
USER app
EXPOSE 8000
ENTRYPOINT ["sh", "/app/backend-entrypoint.sh"]
