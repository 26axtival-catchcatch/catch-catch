import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("target", "seed_path", "source_override"),
    [
        ("dev", "data/seeding/hackathon-2week", None),
        ("dev-bedrock", "data/custom seed", None),
        ("dev", "data/seeding/hackathon-2week", "data/custom sources"),
    ],
)
def test_make_dev_seeds_before_launch_and_passes_source_directory(
    tmp_path: Path, target: str, seed_path: str, source_override: str | None
) -> None:
    shutil.copyfile(REPOSITORY_ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "backend").symlink_to(REPOSITORY_ROOT / "backend", target_is_directory=True)
    (tmp_path / "scripts").mkdir()
    # Replace only the long-running server launch; execute the real seed CLI.
    (tmp_path / "scripts/dev.sh").write_text(
        f"exec {shlex.quote(sys.executable)} - \"$1\" <<'PY'\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "source_dir = Path(os.environ.get('ONBOARDED_SOURCES_DIR', 'missing'))\n"
        "Path('launched.json').write_text(json.dumps({\n"
        "    'mode': sys.argv[1], 'source_dir': str(source_dir),\n"
        "    'seed_ready': Path(os.environ['EXPECTED_SEED_PATH'], 'manifest.json').is_file(),\n"
        "    'sources': sorted(p.parent.name for p in source_dir.glob('*/spec.json')),\n"
        "}))\n"
        "PY\n",
        encoding="utf-8",
    )
    environment = {k: v for k, v in os.environ.items() if k != "ONBOARDED_SOURCES_DIR"}
    environment["EXPECTED_SEED_PATH"] = seed_path
    if source_override is not None:
        environment["ONBOARDED_SOURCES_DIR"] = source_override

    subprocess.run(
        ["make", target, f"HACKATHON_SEED_PATH={seed_path}"],
        cwd=tmp_path, env=environment, check=True, capture_output=True, text=True,
    )

    launched = json.loads((tmp_path / "launched.json").read_text())
    assert launched["seed_ready"] is True
    assert launched["mode"] == "bedrock"
    assert launched["source_dir"] == (source_override or f"{seed_path}/onboarded-sources")
    if source_override is None:
        assert set(launched["sources"]) == {
            "hackathon_app_behavior",
            "hackathon_billing_profile",
            "hackathon_crm_campaign",
            "hackathon_roaming_usage",
            "hackathon_search_feedback",
            "hackathon_search_history",
            "hackathon_vas_subscription",
            "hackathon_voc",
        }


def _normalized(path: Path) -> str:
    content = path.read_text(encoding="utf-8").replace("\\\n", " ")
    return " ".join(content.split())


def test_dev_launcher_loads_env_before_python_process_starts() -> None:
    launcher = _normalized(REPOSITORY_ROOT / "scripts" / "dev.sh")

    assert '"${env_isolation[@]}" uv run "${env_args[@]}" --project backend uvicorn' in launcher
    assert "env -u LANGSMITH_PROJECT" in launcher


def test_fixture_launcher_loads_env_before_python_process_starts() -> None:
    makefile = _normalized(REPOSITORY_ROOT / "Makefile")

    assert (
        '"$${env_isolation[@]}" uv run "$${env_args[@]}" --project backend uvicorn'
        in makefile
    )
    assert "env -u LANGSMITH_PROJECT" in makefile


def test_frontend_launchers_strip_provider_and_tracing_settings() -> None:
    launcher = _normalized(REPOSITORY_ROOT / "scripts" / "dev.sh")
    makefile = _normalized(REPOSITORY_ROOT / "Makefile")

    assert '"${frontend_env_isolation[@]}" npm --prefix frontend run dev' in launcher
    assert 'env -u GEMINI_API_KEY -u GOOGLE_API_KEY' in launcher
    assert 'env -u GEMINI_API_KEY -u GOOGLE_API_KEY' in makefile
    assert '-u LANGSMITH_API_KEY' in launcher
    assert '-u LANGCHAIN_API_KEY' in launcher
    assert '-u LANGSMITH_API_KEY' in makefile
    assert '-u LANGCHAIN_API_KEY' in makefile
    assert '-u LANGFUSE_SECRET_KEY' in launcher
    assert '-u LANGFUSE_PUBLIC_KEY' in launcher
    assert '-u LANGFUSE_BASE_URL' in launcher
    assert '-u LANGFUSE_SECRET_KEY' in makefile
    assert '-u LANGFUSE_PUBLIC_KEY' in makefile
    assert '-u LANGFUSE_BASE_URL' in makefile
    assert '-u AWS_BEARER_TOKEN_BEDROCK' in launcher
    assert '-u AWS_BEARER_TOKEN_BEDROCK' in makefile


def test_backend_launchers_prefer_selected_langfuse_env_file() -> None:
    launcher = _normalized(REPOSITORY_ROOT / "scripts" / "dev.sh")
    makefile = _normalized(REPOSITORY_ROOT / "Makefile")

    for variable in (
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_DEBUG",
        "LANGFUSE_TRACING_ENVIRONMENT",
        "LANGFUSE_RELEASE",
    ):
        assert f"-u {variable}" in launcher
        assert f"-u {variable}" in makefile


def test_uv_env_file_enables_langsmith_in_a_clean_subprocess(tmp_path: Path) -> None:
    env_file = tmp_path / "launcher.env"
    env_file.write_text(
        "LANGSMITH_TRACING=true\n"
        "LANGSMITH_API_KEY=test-key\n"
        "LANGSMITH_PROJECT=launcher-test\n",
        encoding="utf-8",
    )
    clean_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("LANGSMITH_", "LANGCHAIN_"))
    }
    uv = shutil.which("uv")
    assert uv is not None

    result = subprocess.run(
        [
            uv,
            "run",
            "--env-file",
            str(env_file),
            "--project",
            "backend",
            "python",
            "-c",
            (
                "from langsmith.utils import tracing_is_enabled; "
                "print(tracing_is_enabled())"
            ),
        ],
        cwd=REPOSITORY_ROOT,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "True"
