import gzip
import os
import sqlite3
import tempfile
import unittest
import urllib.error
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

from hermes import backup as bk
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))
PASSWORD = "una frase larga de prueba"
SAS = "https://cuenta.blob.core.windows.net/hermes-backups?sv=2023&sig=SECRETO"


class BackupBase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.db = self.dir / "hermes.db"
        self.work = self.dir / "tmp"
        self.store = Store(self.db)
        self.store.add_fact("Mi contador se llama Luis", 1)
        self.moment = datetime(2026, 11, 11, 4, 0, tzinfo=TZ)
        self.uploads = []
        self.alerts = []
        self.upload_error = None
        self.alert_error = None
        self.service = bk.BackupService(
            self.store, self.db, self.work, PASSWORD, time(3, 0), self._send, self._upload, now=lambda: self.moment
        )

    def tearDown(self):
        self.store._conn.close()
        self._dir.cleanup()

    def _upload(self, name, data):
        if self.upload_error:
            raise self.upload_error
        self.uploads.append((name, data))

    def _send(self, text, buttons):
        if self.alert_error:
            raise self.alert_error
        self.alerts.append(text)


class CryptoTests(BackupBase):
    def test_round_trip(self):
        self.assertEqual(bk.decrypt(bk.encrypt(b"datos", PASSWORD), PASSWORD), b"datos")

    def test_wrong_password_is_rejected(self):
        with self.assertRaisesRegex(bk.BackupError, "incorrecta"):
            bk.decrypt(bk.encrypt(b"datos", PASSWORD), "otra contraseña larga")

    def test_tampered_file_is_rejected(self):
        blob = bytearray(bk.encrypt(b"datos", PASSWORD))
        blob[-1] ^= 1
        with self.assertRaises(bk.BackupError):
            bk.decrypt(bytes(blob), PASSWORD)

    def test_tampered_header_is_rejected(self):
        blob = bytearray(bk.encrypt(b"datos", PASSWORD))
        blob[len(bk.MAGIC) + bk.SALT_BYTES] ^= 1
        with self.assertRaises(bk.BackupError):
            bk.decrypt(bytes(blob), PASSWORD)

    def test_not_a_backup(self):
        with self.assertRaisesRegex(bk.BackupError, "no es un respaldo"):
            bk.decrypt(b"cualquier cosa", PASSWORD)

    def test_each_encryption_is_different(self):
        self.assertNotEqual(bk.encrypt(b"datos", PASSWORD), bk.encrypt(b"datos", PASSWORD))


class SnapshotTests(BackupBase):
    def test_uploaded_file_does_not_contain_plaintext_and_restores(self):
        name, _ = self.service.backup()
        self.assertEqual(name, "hermes-2026-11-11.db.gz.enc")
        blob = self.uploads[0][1]
        self.assertNotIn(b"Luis", blob)
        backup_file = self.dir / "copia.enc"
        backup_file.write_bytes(blob)
        restored = self.dir / "restaurada.db"
        bk.restore_backup(backup_file, restored, PASSWORD)
        connection = sqlite3.connect(restored)
        self.assertEqual(connection.execute("SELECT text FROM facts").fetchone()[0], "Mi contador se llama Luis")
        connection.close()

    def test_snapshot_includes_uncheckpointed_wal_data(self):
        self.store.add_fact("Dato reciente", 2)
        data = gzip.decompress(bk.snapshot_database(self.db, self.work))
        self.assertIn(b"Dato reciente", data)

    def test_no_unencrypted_temporary_files_remain(self):
        self.service.backup()
        self.assertEqual(os.listdir(self.work), [])

    def test_restore_refuses_to_overwrite(self):
        self.service.backup()
        backup_file = self.dir / "copia.enc"
        backup_file.write_bytes(self.uploads[0][1])
        with self.assertRaisesRegex(bk.BackupError, "Ya existe"):
            bk.restore_backup(backup_file, self.db, PASSWORD)

    def test_corrupt_data_is_never_uploaded(self):
        with mock.patch.object(bk, "snapshot_database", return_value=gzip.compress(b"no es sqlite" * 400)):
            with self.assertRaises(bk.BackupError):
                self.service.backup()
        self.assertEqual(self.uploads, [])


class ScheduleTests(BackupBase):
    def test_not_before_backup_time(self):
        self.moment = datetime(2026, 11, 11, 2, 59, tzinfo=TZ)
        self.service.tick()
        self.assertEqual(self.uploads, [])

    def test_once_per_day(self):
        self.service.tick()
        self.service.tick()
        self.assertEqual(len(self.uploads), 1)
        self.moment += timedelta(days=1)
        self.service.tick()
        self.assertEqual(len(self.uploads), 2)

    def test_catches_up_if_machine_was_off_at_backup_time(self):
        self.moment = datetime(2026, 11, 11, 18, 0, tzinfo=TZ)
        self.service.tick()
        self.assertEqual(len(self.uploads), 1)

    def test_failure_alerts_once_and_retries_hourly(self):
        self.upload_error = bk.BackupError("Azure respondió HTTP 403")
        with self.assertLogs("hermes.backup", level="WARNING"):
            self.service.tick()
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("HTTP 403", self.alerts[0])
        self.moment += timedelta(minutes=30)
        self.service.tick()
        self.assertEqual(len(self.alerts), 1)
        self.moment += timedelta(minutes=31)
        with self.assertLogs("hermes.backup", level="WARNING"):
            self.service.tick()
        self.assertEqual(len(self.alerts), 1)
        self.upload_error = None
        self.moment += timedelta(minutes=61)
        self.service.tick()
        self.assertEqual(len(self.uploads), 1)

    def test_alert_retried_if_telegram_was_down(self):
        self.upload_error = bk.BackupError("x")
        self.alert_error = OSError("sin red")
        with self.assertLogs("hermes.backup", level="WARNING"):
            self.service.tick()
        self.assertEqual(self.alerts, [])
        self.alert_error = None
        self.moment += timedelta(minutes=61)
        with self.assertLogs("hermes.backup", level="WARNING"):
            self.service.tick()
        self.assertEqual(len(self.alerts), 1)

    def test_unexpected_error_alert_does_not_leak_details(self):
        self.upload_error = ValueError(SAS)
        with self.assertLogs("hermes.backup", level="WARNING"):
            self.service.tick()
        self.assertNotIn("SECRETO", self.alerts[0])


class AzureTests(unittest.TestCase):
    def test_blob_url_keeps_sas_query(self):
        self.assertEqual(
            bk.blob_url(SAS, "hermes-2026-11-11.db.gz.enc"),
            "https://cuenta.blob.core.windows.net/hermes-backups/hermes-2026-11-11.db.gz.enc?sv=2023&sig=SECRETO",
        )

    def test_plain_http_is_rejected(self):
        with self.assertRaises(bk.BackupError):
            bk.blob_url("http://cuenta/x?sig=1", "a")

    def test_url_without_sas_is_rejected(self):
        with self.assertRaises(bk.BackupError):
            bk.blob_url("https://cuenta/x", "a")

    def test_upload_sends_block_blob_headers(self):
        with mock.patch.object(bk.urllib.request, "urlopen") as urlopen:
            bk.upload_to_azure(SAS, "a.enc", b"x")
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.get_header("X-ms-blob-type"), "BlockBlob")

    def test_errors_do_not_contain_the_sas(self):
        error = urllib.error.HTTPError(bk.blob_url(SAS, "a"), 403, "Forbidden", {}, None)
        with mock.patch.object(bk.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(bk.BackupError) as caught:
                bk.upload_to_azure(SAS, "a.enc", b"x")
        self.assertNotIn("SECRETO", str(caught.exception))
        self.assertIn("403", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
