#!/usr/bin/env python3
"""Local Compose lifecycle. Never print generated credentials or resolved config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local" / "compose"
PREFIXES = ("LANGSMITH_", "LANGCHAIN_", "LANGFUSE_", "GEMINI_", "GOOGLE_", "AWS_", "BEDROCK_")
PROVIDER_KEYS = (
    "AGENT_MODE", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODEL", "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION",
    "AWS_DEFAULT_REGION", "BEDROCK_MODEL", "BEDROCK_INVESTIGATOR_MODEL",
)


def read_env(path: Path) -> dict[str, str]:
    """Read our generated raw KEY=value files, never arbitrary shell syntax."""
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#"))


def write_private(path: Path, values: dict[str, str]) -> None:
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Multiline environment values are unsupported")
    # Atomic replacement also ensures old permissive files become private.
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(temporary, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    temporary.replace(path)


def selected_env() -> Path | None:
    explicit = os.environ.get("ENV_FILE")
    if explicit:
        path = Path(explicit).expanduser()
        path = path if path.is_absolute() else ROOT / path
        if not path.is_file():
            raise ValueError("ENV_FILE does not exist")
        return path
    for path in (ROOT / ".env", ROOT / "backend" / ".env"):
        if path.is_file():
            return path
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True).strip())
    common = common if common.is_absolute() else ROOT / common
    for path in (common.resolve().parent / ".env", common.resolve().parent / "backend/.env"):
        if path.is_file():
            return path
    return None


def initialize() -> None:
    path = selected_env()
    environment = dict(os.environ)
    if path:
        # uv must load the selected file before Python imports any tracing SDK.
        environment = {key: value for key, value in environment.items()
                       if not key.startswith(PREFIXES) and key not in PROVIDER_KEYS}
    subprocess.run(
        ["uv", "run", *( ["--env-file", str(path)] if path else ["--no-env-file"] ),
         "--project", str(ROOT / "backend"), "python", str(Path(__file__).resolve()),
         "_write-env"], cwd=ROOT, env=environment, check=True,
    )


def write_environment() -> None:
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(LOCAL, 0o700)
    settings_file = LOCAL / "stack.env"
    if settings_file.exists():
        settings = read_env(settings_file)
    else:
        settings = {key: secrets.token_hex(32) for key in (
            "POSTGRES_PASSWORD", "CLICKHOUSE_PASSWORD", "REDIS_PASSWORD", "MINIO_PASSWORD",
            "LANGFUSE_SALT", "LANGFUSE_ENCRYPTION_KEY", "NEXTAUTH_SECRET",
            "LANGFUSE_USER_PASSWORD",
        )}
        settings.update({
            "LANGFUSE_PUBLIC_KEY": "pk-lf-" + secrets.token_hex(16),
            "LANGFUSE_SECRET_KEY": "sk-lf-" + secrets.token_hex(32),
            "LANGFUSE_USER_EMAIL": "admin@catch-catch.local",
            "APP_PORT": "3200", "LANGFUSE_PORT": "3210", "MINIO_PORT": "3290",
            "APP_URL": "http://localhost:3200", "LANGFUSE_URL": "http://localhost:3210",
            "MINIO_URL": "http://localhost:3290",
        })
        write_private(settings_file, settings)
    provider = {key: value for key, value in os.environ.items()
                if key in PROVIDER_KEYS or key.startswith(("LANGSMITH_", "LANGCHAIN_"))}
    has_bedrock = bool(provider.get("AWS_BEARER_TOKEN_BEDROCK", "").strip())
    has_gemini = bool((provider.get("GEMINI_API_KEY") or provider.get("GOOGLE_API_KEY", "")).strip())
    # No keys means the stack remains usable with its deterministic fixture.
    mode = provider.get("AGENT_MODE") or (
        "bedrock" if has_bedrock else "gemini" if has_gemini else "fixture")
    if mode in ("bedrock", "gemini") and not (has_bedrock if mode == "bedrock" else has_gemini):
        raise ValueError("Selected agent mode has no provider credential")
    provider.update({
        "AGENT_MODE": mode,
        "LANGFUSE_PUBLIC_KEY": settings["LANGFUSE_PUBLIC_KEY"],
        "LANGFUSE_SECRET_KEY": settings["LANGFUSE_SECRET_KEY"],
        "LANGFUSE_BASE_URL": "http://langfuse-web:3000",
        "LANGFUSE_TRACING_ENVIRONMENT": "local-compose",
    })
    write_private(LOCAL / "backend.env", provider)
    write_private(LOCAL / "langfuse-login.txt", {
        "URL": settings["LANGFUSE_URL"], "EMAIL": settings["LANGFUSE_USER_EMAIL"],
        "PASSWORD": settings["LANGFUSE_USER_PASSWORD"],
    })
    print(f"Initialized local Compose environment; agent mode: {mode}.")
    print("Langfuse login is saved privately in .local/compose/langfuse-login.txt")


def compose(*args: str, anonymous: bool = False, **kwargs) -> subprocess.CompletedProcess:
    if not (LOCAL / "stack.env").is_file() or not (LOCAL / "backend.env").is_file():
        raise ValueError("Run python3 scripts/compose.py init first")
    # Generated configuration wins over inherited shell variables, including keys.
    settings = read_env(LOCAL / "stack.env")
    environment = {key: value for key, value in os.environ.items()
                   if key not in settings and not key.startswith(PREFIXES)}
    environment["COMPOSE_PARALLEL_LIMIT"] = "1"
    if anonymous:
        # Public-image workaround for a blocked Docker Desktop credential helper.
        # Discover the active engine before switching this subprocess's config.
        endpoint = environment.get("DOCKER_HOST") or subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            text=True, env=environment).strip()
        config = LOCAL / "docker-public"
        config.mkdir(exist_ok=True, mode=0o700)
        (config / "config.json").write_text(json.dumps({
            "auths": {}, "cliPluginsExtraDirs": [str(Path.home() / ".docker/cli-plugins")],
        }))
        environment["DOCKER_CONFIG"] = str(config)
        environment["DOCKER_HOST"] = endpoint
        environment.pop("DOCKER_CONTEXT", None)
    return subprocess.run(
        ["docker", "compose", "--project-name", "catch-catch-local",
         "--env-file", str(LOCAL / "stack.env"),
         "-f", str(ROOT / "compose.yaml"), *args], cwd=ROOT,
        env=environment, check=True, **kwargs,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "_write-env", "build", "up", "down", "ps", "verify"])
    parser.add_argument("--mode", choices=["fixture", "bedrock", "gemini"], default="fixture")
    parser.add_argument("--anonymous-pulls", action="store_true",
                        help="Use public registries without the Docker credential helper")
    args = parser.parse_args()
    if args.action == "init":
        initialize()
    elif args.action == "_write-env":
        write_environment()
    elif args.action == "build":
        compose("build", anonymous=args.anonymous_pulls)
    elif args.action == "up":
        compose("up", "--build", "-d", "--wait", "--wait-timeout", "600",
                anonymous=args.anonymous_pulls)
    elif args.action == "down":
        compose("down")  # Named volumes are intentionally preserved.
    elif args.action == "ps":
        compose("ps")
    elif args.action == "verify":
        subprocess.run(["uv", "run", "--no-env-file", "--project", str(ROOT / "backend"),
                        "python", str(ROOT / "scripts/verify-compose.py"), "--mode", args.mode],
                       cwd=ROOT, check=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        # No expanded command, environment, or provider response is printed.
        print(f"Compose command failed (exit {error.returncode}).", file=sys.stderr)
        sys.exit(error.returncode)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
