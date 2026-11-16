import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes.__main__ import take_home
from hermes.config import Config


class SecondCopyTests(unittest.TestCase):
    def test_home_option_selects_another_data_folder(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_HOME", None)
            self.assertEqual(take_home(["check"]), ["check"])
            self.assertNotIn("HERMES_HOME", os.environ)
            self.assertEqual(take_home(["--home", "C:/otra", "gmail-auth", "trabajo"]), ["gmail-auth", "trabajo"])
            self.assertEqual(os.environ["HERMES_HOME"], "C:/otra")
            self.assertEqual(take_home(["check", "--home", "C:/otra"]), ["check"])
            with self.assertRaises(SystemExit):
                take_home(["--home"])

    def test_each_copy_reads_only_its_own_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, ".env").write_text(
                "TELEGRAM_BOT_TOKEN=bot-de-prueba\nHERMES_LOCK_PORT=47831\nHERMES_STATUS_PORT=47832\nHERMES_HOME_VOICE=off\n",
                encoding="utf-8",
            )
            clean = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "TELEGRAM_", "TAVILY_", "AZURE_"))}
            with mock.patch.dict(os.environ, {**clean, "HERMES_HOME": folder}, clear=True):
                config = Config.load()
            self.assertEqual((config.lock_port, config.status_port, config.home_voice_enabled), (47831, 47832, False))
            self.assertEqual(config.telegram_token, "bot-de-prueba")
            self.assertEqual(config.db_path, Path(folder) / "data" / "hermes.db")
            self.assertEqual(config.gmail_token_path, Path(folder) / "google-token.json")
            self.assertEqual((config.public_host, config.page_password, config.allowed_chat_id), ("", "", None))

    def test_default_lock_port_is_unchanged(self):
        self.assertEqual(Config.__dataclass_fields__["lock_port"].default, 47821)


if __name__ == "__main__":
    unittest.main()
