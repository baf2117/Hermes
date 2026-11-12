import json
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hermes import claude_cli as cc
from hermes import llm as llm_module
from hermes.claude_cli import COOLDOWN_SECONDS, ClaudeCodeClient, ClaudeUnavailable, HybridLLM
from hermes.llm import OllamaClient, reply_messages
from hermes.status import VoiceStatus
from hermes.store import LLMUsage, Store

OK = {
    "type": "result", "is_error": False, "result": "Hola.", "total_cost_usd": 0.0123,
    "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 40},
    "modelUsage": {"claude-opus-5-5": {}},
}
MESSAGES = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "pregunta"}]


def finished(payload=OK, code=0, raw=None):
    return SimpleNamespace(stdout=raw if raw is not None else json.dumps(payload), returncode=code)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.usage = []
        self.client = ClaudeCodeClient("claude", "claude-opus-5-5", Path(self._dir.name) / "w", self.usage.append)

    def tearDown(self):
        self._dir.cleanup()

    def run_with(self, **kwargs):
        with mock.patch.object(cc.subprocess, "run", **kwargs) as run:
            result = self.client.complete(MESSAGES, "conversación")
        return result, run

    def test_runs_with_every_tool_disabled(self):
        _, run = self.run_with(return_value=finished())
        command = run.call_args[0][0]
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--setting-sources") + 1], "")
        for flag in ("--print", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--system-prompt") + 1], "sistema")
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_prompt_goes_through_stdin(self):
        _, run = self.run_with(return_value=finished())
        self.assertEqual(run.call_args.kwargs["input"], "pregunta")

    def test_runs_in_empty_private_folder(self):
        _, run = self.run_with(return_value=finished())
        self.assertEqual(run.call_args.kwargs["cwd"], self.client.work_dir)
        self.assertTrue(self.client.work_dir.is_dir())

    def test_api_credentials_are_never_passed(self):
        with mock.patch.dict(cc.os.environ, {"ANTHROPIC_API_KEY": "x", "ANTHROPIC_AUTH_TOKEN": "y", "OTRA": "z"}):
            _, run = self.run_with(return_value=finished())
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", environment)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", environment)
        self.assertEqual(environment["OTRA"], "z")

    def test_records_tokens(self):
        result, _ = self.run_with(return_value=finished())
        self.assertEqual(result, "Hola.")
        usage = self.usage[0]
        self.assertEqual((usage.provider, usage.purpose, usage.model), ("claude", "conversación", "claude-opus-5-5"))
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens), (10, 20, 300, 40))
        self.assertAlmostEqual(usage.cost_usd, 0.0123)

    def test_failures_become_unavailable_and_record_nothing(self):
        cases = [
            dict(return_value=finished({"is_error": True, "result": "Límite alcanzado"})),
            dict(return_value=finished(code=1)),
            dict(return_value=finished(raw="no es json")),
            dict(return_value=finished({"is_error": False, "result": "   "})),
            dict(side_effect=subprocess.TimeoutExpired("claude", 90)),
            dict(side_effect=FileNotFoundError()),
        ]
        for case in cases:
            with self.assertRaises(ClaudeUnavailable):
                self.run_with(**case)
        self.assertEqual(self.usage, [])

    def test_history_is_flattened(self):
        messages = reply_messages("¿y mañana?", [("user", "hola"), ("hermes", "buenas")], "")
        self.assertEqual(cc._flatten(messages), "Usuario: hola\n\nHermes: buenas\n\nUsuario: ¿y mañana?")


class FakeLocal:
    def __init__(self):
        self.calls = []

    def interpret(self, *args, **kwargs):
        self.calls.append("interpret")
        return {"intent": "chat"}

    def reply(self, text, history, memory=""):
        self.calls.append("reply")
        return "local"

    def answer_from_web(self, *args):
        self.calls.append("web")
        return "local web"


class FakeClaude:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def complete(self, messages, purpose):
        self.calls.append(purpose)
        if self.error:
            raise self.error
        return "claude"


class HybridTests(unittest.TestCase):
    def build(self, error=None):
        self.time = 1000.0
        self.local, self.claude = FakeLocal(), FakeClaude(error)
        return HybridLLM(self.local, self.claude, clock=lambda: self.time)

    def test_interpretation_stays_local(self):
        llm = self.build()
        llm.interpret("x")
        self.assertEqual(self.claude.calls, [])

    def test_chat_uses_claude(self):
        self.assertEqual(self.build().reply("hola", []), "claude")
        self.assertEqual(self.local.calls, [])

    def test_web_answers_use_claude(self):
        result = SimpleNamespace(title="t", content="c")
        now = datetime(2026, 11, 10, tzinfo=timezone(timedelta(hours=-6)))
        self.assertEqual(self.build().answer_from_web("q", "b", [result], now), "claude")

    def test_falls_back_when_unavailable(self):
        llm = self.build(ClaudeUnavailable("sin suscripción"))
        with self.assertLogs("hermes.claude_cli", level="WARNING"):
            self.assertEqual(llm.reply("hola", []), "local")

    def test_cooldown_avoids_retrying_every_message(self):
        llm = self.build(ClaudeUnavailable("x"))
        with self.assertLogs("hermes.claude_cli", level="WARNING"):
            llm.reply("a", [])
        llm.reply("b", [])
        self.assertEqual(len(self.claude.calls), 1)

    def test_retries_after_cooldown(self):
        llm = self.build(ClaudeUnavailable("x"))
        with self.assertLogs("hermes.claude_cli", level="WARNING"):
            llm.reply("a", [])
        self.claude.error = None
        self.time += COOLDOWN_SECONDS + 1
        self.assertEqual(llm.reply("b", []), "claude")


class WarmUpTests(unittest.TestCase):
    def client(self):
        return OllamaClient("http://x", "hermes", timeout=1)

    def test_loads_model_and_keeps_it(self):
        with mock.patch.object(llm_module.urllib.request, "urlopen") as urlopen:
            self.assertTrue(self.client().warm_up(threading.Event()))
        body = json.loads(urlopen.call_args[0][0].data)
        self.assertEqual(body, {"model": "hermes", "keep_alive": -1})

    def test_retries_until_ollama_is_ready(self):
        stop = mock.Mock()
        stop.wait.return_value = False
        effects = [OSError("aún no"), OSError("aún no"), mock.MagicMock()]
        with mock.patch.object(llm_module.urllib.request, "urlopen", side_effect=effects):
            self.assertTrue(self.client().warm_up(stop))
        self.assertEqual(stop.wait.call_count, 2)

    def test_gives_up_when_stopping(self):
        stop = mock.Mock()
        stop.wait.return_value = True
        with mock.patch.object(llm_module.urllib.request, "urlopen", side_effect=OSError("no")):
            self.assertFalse(self.client().warm_up(stop))

    def test_hybrid_warms_the_local_model(self):
        local = mock.Mock()
        local.warm_up.return_value = True
        self.assertTrue(HybridLLM(local, FakeClaude()).warm_up(threading.Event()))
        local.warm_up.assert_called_once()

    def test_every_request_keeps_the_model_loaded(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"message": {"content": "hola"}}).encode()
        with mock.patch.object(llm_module.urllib.request, "urlopen", return_value=response) as urlopen:
            self.client().reply("x", [])
        self.assertEqual(json.loads(urlopen.call_args[0][0].data)["keep_alive"], -1)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def test_totals_are_grouped_by_period_and_provider(self):
        self.store.add_usage(LLMUsage("claude", "conversación", 10, 20, 300, 40, 0.5, "m"), 500)
        self.store.add_usage(LLMUsage("claude", "búsqueda", 1, 2, 0, 0, 0.1, "m"), 1500)
        self.store.add_usage(LLMUsage("local", "interpretar", 100, 5, model="hermes"), 1500)
        summary = self.store.usage_summary(1000, 0)
        self.assertEqual(summary["today"]["claude"]["calls"], 1)
        self.assertEqual(summary["today"]["claude"]["input"], 1)
        self.assertEqual(summary["month"]["claude"]["calls"], 2)
        self.assertEqual(summary["month"]["claude"]["cache_read"], 300)
        self.assertAlmostEqual(summary["month"]["claude"]["cost"], 0.6)
        self.assertEqual(summary["today"]["local"]["output"], 5)
        self.assertEqual(summary["recent"][0]["provider"], "local")

    def test_empty(self):
        self.assertEqual(self.store.usage_summary(0, 0), {"today": {}, "month": {}, "recent": []})

    def test_status_includes_usage_and_caches_it(self):
        status, calls = VoiceStatus(), []
        status.set_usage_source(lambda: calls.append(1) or {"today": {}})
        self.assertEqual(status.snapshot()["tokens"], {"today": {}})
        status.snapshot()
        self.assertEqual(len(calls), 1)

    def test_status_survives_usage_errors(self):
        status = VoiceStatus()
        status.set_usage_source(lambda: 1 / 0)
        with self.assertLogs("hermes.status", level="ERROR"):
            self.assertEqual(status.snapshot()["tokens"], {})


if __name__ == "__main__":
    unittest.main()
