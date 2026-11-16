import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from hermes.assistant import Reply
from hermes.followup import MailFollowup
from hermes.gmail import GmailError, ThreadMessage
from hermes.scheduler import SUMMARY_KEY
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 16, 9, 40, tzinfo=TZ)


def ts(days_ago):
    return int((NOW - timedelta(days=days_ago)).timestamp())


def msg(mid, days_ago, sent, to=(), sender="", subject="Asunto"):
    return ThreadMessage(mid, ts(days_ago), sent, sender, list(to), subject)


class FakeGmail:
    def __init__(self):
        self.threads = {
            # Te toca contestar: Ana escribió hace 5 días y no contestaste.
            "t-ana": [msg("a1", 5, False, sender="Ana López <ana@x.com>", subject="Cotización")],
            # Ya contestaste: no cuenta.
            "t-luis": [msg("l1", 6, False, sender="Luis <luis@x.com>", subject="Factura"), msg("l2", 5, True, ["Luis <luis@x.com>"])],
            # Te deben respuesta: escribiste hace 4 días.
            "t-juan": [msg("j1", 4, True, ["Juan Pérez <juan@y.com>", "Yo <yo@x.com>"], subject="Contrato")],
            # Muy reciente: todavía no.
            "t-eva": [msg("e1", 1, True, ["Eva <eva@y.com>"], subject="Hola")],
            # A un aviso automático o a ti mismo: no cuenta.
            "t-bot": [msg("b1", 6, True, ["no-reply@banco.com"], subject="Re: aviso")],
            "t-yo": [msg("y1", 6, True, ["yo@x.com"], subject="Nota")],
            # Te contestaron: lo último no es tuyo.
            "t-sol": [msg("s1", 8, True, ["sol@y.com"], subject="Pedido"), msg("s2", 6, False, sender="Sol <sol@y.com>")],
        }
        self.message_threads = {"a1": "t-ana", "l1": "t-luis"}
        self.calls = 0

    def address(self):
        return "yo@x.com"

    def sent_threads(self, after_ts):
        self.calls += 1
        return ["t-juan", "t-eva", "t-bot", "t-yo", "t-sol", "t-luis"]

    def thread_of(self, message_id):
        return self.message_threads[message_id]

    def thread(self, thread_id):
        self.calls += 1
        return self.threads[thread_id]


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.add_email("a1", ts(5), "Ana López <ana@x.com>", "Cotización", "", True)
        self.store.add_email("l1", ts(6), "Luis <luis@x.com>", "Factura", "", True)
        self.store.add_email("z1", ts(5), "Promo <promo@z.com>", "Ofertas", "", False)  # No es importante.
        self.gmail = FakeGmail()
        self.config = SimpleNamespace(followup_enabled=True, followup_days=3)
        self.followup = MailFollowup([("personal", self.gmail)], self.store, self.config, lambda: NOW, Reply)
        self.sent = []
        self.followup.send = lambda text, buttons: self.sent.append((text, buttons))

    def test_report_lists_both_sides(self):
        reply = self.followup.report(NOW)
        self.assertEqual(reply.text, "📬 Correos que esperan respuesta:\nTe toca contestar:\n• Ana López, «Cotización» (hace 5 días)\n"
                                     "Te deben respuesta:\n• Juan Pérez, «Contrato» (hace 4 días)")
        self.assertEqual(reply.buttons, [[("🔕 Ya no me los muestres", "fuhide:20261116")]])

    def test_days_setting_changes_what_counts(self):
        self.config.followup_days = 5
        self.assertNotIn("Juan", self.followup.report(NOW).text)
        self.config.followup_days = 1
        self.assertIn("Eva", self.followup.report(NOW).text)

    def test_hide_them(self):
        reply = self.followup.report(NOW)
        self.assertEqual(self.followup.hide(20261116).text, "Listo, esos ya no te los vuelvo a mencionar.")
        self.assertIn("Nada pendiente", self.followup.report(NOW).text)
        self.assertIn("ya cambió", self.followup.hide(20261115).text)
        self.assertEqual(len(json.loads(self.store.kv_get("followup_hidden"))), 2)

    def test_daily_after_summary_and_not_repeated_within_a_week(self):
        self.followup.tick(NOW)
        self.assertEqual(self.sent, [])  # Antes del resumen de la mañana.
        self.store.kv_set(SUMMARY_KEY, "2026-11-16")
        self.followup.tick(NOW)
        self.followup.tick(NOW + timedelta(hours=1))
        self.assertEqual(len(self.sent), 1)
        tomorrow = NOW + timedelta(days=1)
        self.store.kv_set(SUMMARY_KEY, "2026-11-17")
        self.followup.tick(tomorrow)
        self.assertEqual(len(self.sent), 1)  # Las mismas: no se repiten al día siguiente.
        later = NOW + timedelta(days=8)
        self.store.kv_set(SUMMARY_KEY, later.date().isoformat())
        self.followup.tick(later)
        self.assertEqual(len(self.sent), 2)  # A la semana, si siguen igual, se vuelven a mencionar.

    def test_errors_and_switch(self):
        def broken(after_ts):
            raise GmailError("caído")

        self.gmail.sent_threads = broken
        self.assertIn("Ana López", self.followup.report(NOW).text)  # Lo de una parte no tumba lo demás.
        self.config.followup_enabled = False
        self.assertIn("está apagado", self.followup.report(NOW).text)
        self.store.kv_set(SUMMARY_KEY, "2026-11-16")
        self.followup.tick(NOW)
        self.assertEqual(self.sent, [])

    def test_phrases(self):
        self.assertIn("Te toca contestar", self.followup.handle("¿Qué correos tengo pendientes?", NOW).text)
        self.assertIn("Te deben", self.followup.handle("correos sin respuesta", NOW).text)
        self.assertIsNone(self.followup.handle("manda un correo a Juan", NOW))


class GmailThreadTests(unittest.TestCase):
    def test_reads_only_headers_and_orders_messages(self):
        import tempfile
        from pathlib import Path

        from hermes.gmail import GmailClient

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "client.json").write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "s"}}), encoding="utf-8")
        (root / "token.json").write_text(json.dumps({"refresh_token": "r"}), encoding="utf-8")
        requests = []

        def fetch(request):
            requests.append(request.full_url)
            if "oauth2" in request.full_url:
                return json.dumps({"access_token": "llave", "expires_in": 3600}).encode("utf-8")
            if "/threads/" in request.full_url:
                return json.dumps({"messages": [
                    {"id": "b", "internalDate": "2000", "labelIds": ["SENT"], "payload": {"headers": [
                        {"name": "To", "value": "Ana <ana@x.com>, beto@y.com"}, {"name": "Subject", "value": "Re:  hola"}]}},
                    {"id": "a", "internalDate": "1000", "labelIds": ["INBOX"], "payload": {"headers": [
                        {"name": "From", "value": "Ana <ana@x.com>"}, {"name": "Subject", "value": "hola"}]}},
                ]}).encode("utf-8")
            return json.dumps({"messages": [{"id": "1", "threadId": "t1"}, {"id": "2", "threadId": "t1"},
                                            {"id": "3", "threadId": "../malo"}]}).encode("utf-8")

        client = GmailClient(root / "client.json", root / "token.json", fetch)
        self.assertEqual(client.sent_threads(0), ["t1"])
        first, second = client.thread("t1")
        self.assertEqual((first.id, first.sent, first.sender), ("a", False, "Ana <ana@x.com>"))
        self.assertEqual((second.id, second.sent, second.to, second.subject), ("b", True, ["Ana <ana@x.com>", "beto@y.com"], "Re: hola"))
        self.assertIn("format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject", requests[-1])
        self.assertIn("in%3Asent", requests[1])
        with self.assertRaises(GmailError):
            client.thread("../otra")


if __name__ == "__main__":
    unittest.main()
