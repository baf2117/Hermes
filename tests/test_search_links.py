import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from hermes.assistant import Reply
from hermes.links import Links, UnsafeURL, check_url, page_text
from hermes.search import Everything
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=TZ)  # Domingo.


def ts(days_ago):
    return int((NOW - timedelta(days=days_ago)).timestamp())


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        s = self.store
        s.add_task("Mandar propuesta a Carlos", "trabajo", "alta", None, "", 0)
        done = s.add_task("Llamar a Carlos", "trabajo", "media", None, "", 0)
        s.set_status(done.id, "done", ts(3))
        s.add_task("Comprar leche", "casa", "baja", None, "", 0)
        s.add_fact("Carlos prefiere reuniones cortas", 0)
        s.add_email("m1", ts(2), "Carlos Pérez <carlos@cliente.com>", "Cotización", "Pide precios", True)
        s.add_email("m2", ts(200), "Carlos Pérez <carlos@cliente.com>", "Viejo", "", True)  # Fuera de los 90 días.
        s.add_receipt(0, merchant="Café de Carlos", day="2026-11-10", total=45.5, currency="GTQ", category="comida", items="[]")
        s.add_date("cumpleaños", "Carlos", 3, 4, None, 0)
        s.list_create("súper", 0)
        s.list_add("súper", "Galletas para Carlos", 0)
        self.config = SimpleNamespace(search_enabled=True)
        self.everything = Everything(self.store, self.config, lambda: NOW, Reply)

    def ask(self, text):
        reply = self.everything.handle(text, NOW)
        return reply.text if reply else None

    def test_finds_a_person_everywhere(self):
        text = self.ask("¿Qué sabes de Carlos?")
        self.assertTrue(text.startswith("🔎 Lo que sé de «Carlos»:"))
        for expected in ("📌 Tareas pendientes:\n• Mandar propuesta a Carlos", "✅ Tareas terminadas:\n• Llamar a Carlos · hecha el 12 nov",
                         "🧠 Notas:\n• Carlos prefiere reuniones cortas", "✉️ Correos:\n• 13 nov, Carlos Pérez: «Cotización», Pide precios",
                         "🧾 Gastos:\n• 10 nov, Café de Carlos: 45.50 GTQ", "🎂 Fechas:\n• Cumpleaños de Carlos: 4 de marzo",
                         "📋 Listas:\n• súper: Galletas para Carlos"):
            self.assertIn(expected, text)
        self.assertNotIn("Viejo", text)
        self.assertNotIn("leche", text)

    def test_all_words_must_match_and_accents_do_not_matter(self):
        self.assertIn("Cotización", self.ask("qué hay sobre la cotizacion"))
        self.assertIn("Mandar propuesta", self.ask("que tienes de propuesta carlos"))
        self.assertIn("No encontré nada de «zanahoria»", self.ask("¿Qué sabes de zanahoria?"))
        self.assertIsNone(self.ask("recuérdame llamar a Carlos"))

    def test_command_and_switch(self):
        self.assertIn("Lo que sé de «leche»", self.everything.command("leche").text)
        self.assertIn("Dime qué buscar", self.everything.command(" ").text)
        self.config.search_enabled = False
        self.assertIsNone(self.ask("qué sabes de Carlos"))
        self.assertIn("está apagada", self.everything.command("Carlos").text)


PAGE = """<html><head><title>Ignorado</title><meta property="og:title" content="Cómo cuidar un gecko"></head>
<body><nav>Menú</nav><script>alert(1)</script><p>Los geckos necesitan calor.</p><p>Y agua &amp; comida.</p></body></html>"""


class LinksTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.config = SimpleNamespace(links_enabled=True)
        self.fetched, self.summaries = [], []

        def fetch(url):
            self.fetched.append(url)
            return "https://www.reptiles.example/gecko", PAGE

        def summarize(title, text):
            self.summaries.append((title, text))
            return {"title": "Cuidados del gecko", "summary": "Explica calor, agua y comida. Ver https://malo.example/x"}

        self.links = Links(self.store, summarize, self.config, lambda: NOW, Reply, fetch)

    def test_page_text_strips_code_and_menus(self):
        title, text = page_text(PAGE)
        self.assertEqual(title, "Cómo cuidar un gecko")
        self.assertEqual(text, "Los geckos necesitan calor.\nY agua & comida.")

    def test_link_is_read_summarised_and_saved(self):
        reply = self.links.handle("guárdame esto: https://reptiles.example/gecko#parte", NOW)
        self.assertEqual(reply.text, "📚 Guardado para leer: «Cuidados del gecko» (reptiles.example)\nExplica calor, agua y comida. Ver")
        (link,) = self.store.links()
        self.assertEqual((link["url"], link["site"], link["read_at"]), ("https://reptiles.example/gecko", "reptiles.example", None))
        self.assertEqual(reply.buttons, [[("✓ Ya lo leí", f"linkread:{link['id']}"), ("🗑 Quitar", f"linkdel:{link['id']}")]])
        self.assertEqual(self.summaries[0][1], "Los geckos necesitan calor.\nY agua & comida.")
        self.assertIn("ya lo tenías guardado", self.links.handle("https://reptiles.example/gecko", NOW).text)
        self.assertEqual(len(self.fetched), 1)

    def test_unreachable_page_is_still_saved_and_unsafe_is_refused(self):
        def down(url):
            raise OSError("caída")

        self.links.fetch = down
        self.assertIn("No pude abrir la página", self.links.save("https://caida.example/a").text)

        def unsafe(url):
            raise UnsafeURL("privada")

        self.links.fetch = unsafe
        self.assertIn("No abro esa dirección", self.links.save("http://127.0.0.1:47822/").text)
        self.assertEqual(len(self.store.links()), 1)

    def test_model_failure_keeps_the_page_title(self):
        def broken(title, text):
            raise RuntimeError("sin modelo")

        self.links.summarize = broken
        self.assertEqual(self.links.save("https://reptiles.example/gecko").text, "📚 Guardado para leer: «Cómo cuidar un gecko» (reptiles.example)")

    def test_read_remove_report_and_sunday(self):
        self.links.save("https://reptiles.example/gecko")
        link = self.store.links()[0]
        self.assertIn("Para leer (1)", self.links.handle("¿qué tengo para leer?", NOW).text)
        self.assertEqual(self.links.sunday_lines(NOW.date()), [
            "📚 Tienes 1 enlace sin leer; el más viejo es «Cuidados del gecko», de hoy. Míralos con /leer."])
        self.assertEqual(self.links.sunday_lines((NOW + timedelta(days=1)).date()), [])  # Solo los domingos.
        self.assertIn("Marcado como leído", self.links.mark_read(link["id"]).text)
        self.assertIn("No tienes enlaces pendientes", self.links.report().text)
        self.assertIn("Quité", self.links.remove(link["id"]).text)
        self.assertEqual(self.store.links(), [])

    def test_text_with_a_link_inside_is_not_hijacked(self):
        self.assertIsNone(self.links.handle("recuérdame revisar https://x.example mañana", NOW))

    def test_page_actions_and_switch(self):
        self.assertIn("Guardado para leer", self.links.apply({"action": "add", "url": "https://reptiles.example/gecko"})["message"])
        link_id = self.store.links()[0]["id"]
        self.links.apply({"action": "read", "id": link_id})
        self.assertIsNotNone(self.store.get_link(link_id)["read_at"])
        self.links.apply({"action": "unread", "id": link_id})
        self.assertIsNone(self.store.get_link(link_id)["read_at"])
        for bad in ({"action": "add", "url": "javascript:alert(1)"}, {"action": "add", "url": "ftp://x"}, {"action": "read", "id": 99}):
            with self.assertRaises(ValueError, msg=bad):
                self.links.apply(bad)
        self.config.links_enabled = False
        self.assertIsNone(self.links.handle("https://otra.example", NOW))
        self.assertFalse(self.links.snapshot()["enabled"])


class CheckUrlTests(unittest.TestCase):
    def resolve(self, *addresses):
        return mock.patch("hermes.links.socket.getaddrinfo", return_value=[(0, 0, 0, "", (a, 443)) for a in addresses])

    def test_only_public_web_addresses(self):
        with self.resolve("93.184.216.34"):
            self.assertEqual(check_url("https://example.com/a"), "https://example.com/a")
        for address in ("127.0.0.1", "192.168.1.10", "10.0.0.5", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"):
            with self.resolve(address), self.assertRaises(UnsafeURL, msg=address):
                check_url("https://parece-publico.example/")
        with self.resolve("93.184.216.34", "127.0.0.1"), self.assertRaises(UnsafeURL):
            check_url("https://mitad.example/")  # Basta una dirección privada.
        for url in ("file:///C:/secreto", "ftp://x.example/", "https://user:pw@x.example/", "https://x.example:47822/"):
            with self.resolve("93.184.216.34"), self.assertRaises(UnsafeURL, msg=url):
                check_url(url)


if __name__ == "__main__":
    unittest.main()
