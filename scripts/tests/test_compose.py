"""Environment isolation and idempotency checks without Docker or live providers."""

import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("compose", Path(__file__).parents[1] / "compose.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ComposeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.local = Path(self.directory.name)
        self.local_patch = patch.object(module, "LOCAL", self.local)
        self.local_patch.start()
        self.addCleanup(self.local_patch.stop)

    def test_keys_are_stable_private_and_provider_settings_are_isolated(self):
        environment = {
            "GEMINI_API_KEY": "synthetic-test-key-$literal#value",
            "LANGFUSE_SECRET_KEY": "unrelated-existing-project",
            "LANGFUSE_BASE_URL": "http://existing-service",
            "UNRELATED_SECRET": "must-not-be-copied",
            "LANGSMITH_TRACING": "true",
            "BEDROCK_INVESTIGATOR_MODEL": "us.anthropic.claude-sonnet-4-6",
        }
        with patch.dict(os.environ, environment, clear=True):
            module.write_environment()
            before = module.read_env(self.local / "stack.env")
            module.write_environment()
        self.assertEqual(before, module.read_env(self.local / "stack.env"))
        backend = module.read_env(self.local / "backend.env")
        self.assertEqual(backend["GEMINI_API_KEY"], environment["GEMINI_API_KEY"])
        self.assertEqual(backend["LANGSMITH_TRACING"], "true")
        self.assertEqual(backend["BEDROCK_INVESTIGATOR_MODEL"],
                         environment["BEDROCK_INVESTIGATOR_MODEL"])
        self.assertEqual(backend["LANGFUSE_SECRET_KEY"], before["LANGFUSE_SECRET_KEY"])
        self.assertEqual(backend["LANGFUSE_BASE_URL"], "http://langfuse-web:3000")
        self.assertEqual(backend["AGENT_MODE"], "gemini")
        self.assertNotIn("UNRELATED_SECRET", backend)
        for file in self.local.glob("*"):
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_no_keys_uses_fixture(self):
        with patch.dict(os.environ, {}, clear=True):
            module.write_environment()
        self.assertEqual(module.read_env(self.local / "backend.env")["AGENT_MODE"], "fixture")

    def test_explicit_env_removes_inherited_tracing_before_uv_starts(self):
        selected = self.local / "input.env"
        selected.touch()
        environment = {"LANGSMITH_PROJECT": "wrong-shell-project",
                       "LANGCHAIN_TRACING_V2": "false", "GEMINI_API_KEY": "wrong-shell-key"}
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(module, "selected_env", return_value=selected), \
             patch.object(module.subprocess, "run") as run:
            module.initialize()
        call = run.call_args
        self.assertIn("--env-file", call.args[0])
        self.assertNotIn("LANGSMITH_PROJECT", call.kwargs["env"])
        self.assertNotIn("LANGCHAIN_TRACING_V2", call.kwargs["env"])
        self.assertNotIn("GEMINI_API_KEY", call.kwargs["env"])

    def test_missing_model_credentials_fail_without_writing_backend_env(self):
        with patch.dict(os.environ, {"AGENT_MODE": "bedrock"}, clear=True):
            with self.assertRaises(ValueError):
                module.write_environment()
        self.assertFalse((self.local / "backend.env").exists())

    def test_newline_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            module.write_private(self.local / "backend.env", {"KEY": "value\nINJECTED=value"})


if __name__ == "__main__":
    unittest.main()
