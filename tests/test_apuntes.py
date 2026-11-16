"""La pestaña «Apuntes»: listas, notas, hábitos, fechas y esperas manejadas desde la página."""
import http.client
import json
import re
from datetime import datetime

from hermes.extrasedit import ApunteError, ExtrasEditor
from hermes.status import VoiceStatus, start_status_server
from tests.test_core import TZ, Harness
from tests.test_status import free_port


class ApuntesTests(Harness):
    def setUp(self):
        super().setUp()
        self.llm.fail = True
        self.editor = ExtrasEditor(self.assistant)

    def do(self, action, **fields):
        return self.editor.apply({"action": action, **fields})["message"]

    def test_lists_keep_items_literal(self):
        self.do("list_add", list="Súper", text="pan y queso")  # Desde la página no se parte por la «y».
        self.do("list_add", list="súper", text="leche")
        self.do("list_add", list="viaje", text="pasaporte")
        lists = self.editor.snapshot()["lists"]
        self.assertEqual([(entry["name"], [i["text"] for i in entry["items"]]) for entry in lists],
                         [("super", ["pan y queso", "leche"]), ("viaje", ["pasaporte"])])
        with self.assertRaises(ApunteError):
            self.do("list_add", list="super", text="Leche")
        self.do("list_remove", id=lists[0]["items"][0]["id"])
        self.assertIn("Vacié", self.do("list_clear", list="viaje"))
        # Vaciar deja el cajón; eliminar se lo lleva.
        self.assertEqual([(e["name"], len(e["items"])) for e in self.editor.snapshot()["lists"]], [("super", 1), ("viaje", 0)])
        self.assertIn("Eliminé", self.do("list_delete", list="viaje"))
        self.assertEqual([entry["name"] for entry in self.editor.snapshot()["lists"]], ["super"])
        self.assertIn("leche", self.assistant.handle_text("qué hay en la lista del súper").text)  # La misma lista que por chat.

    def test_lists_are_created_empty_and_deleted_whole(self):
        self.assertEqual(self.do("list_create", list="  Súper  "), "Creé la lista de super.")
        self.assertEqual(self.editor.snapshot()["lists"], [{"name": "super", "items": []}])
        with self.assertRaises(ApunteError):
            self.do("list_create", list="super")
        with self.assertRaises(ApunteError):
            self.do("list_create", list="   ")
        self.do("list_add", list="super", text="leche")
        self.do("list_create", list="viaje")
        self.assertEqual([e["name"] for e in self.editor.snapshot()["lists"]], ["super", "viaje"])  # En el orden en que se crearon.
        self.assertIn("vacía", self.assistant.handle_text("qué hay en la lista de viaje").text)
        self.assertIn("• viaje (0)", self.assistant.handle_text("qué listas tengo").text)
        self.do("list_delete", list="super")
        self.assertEqual(self.store.list_items("super"), [])
        with self.assertRaises(ApunteError):
            self.do("list_delete", list="super")

    def test_list_items_can_be_corrected(self):
        self.do("list_add", list="super", text="lehce")
        self.do("list_add", list="super", text="pan")
        first, second = self.editor.snapshot()["lists"][0]["items"]
        self.assertEqual(self.do("list_edit", id=first["id"], text="  leche   entera "), "Guardado.")
        self.do("list_edit", id=first["id"], text="Leche entera")  # Cambiar solo mayúsculas no choca consigo mismo.
        self.assertEqual([i["text"] for i in self.editor.snapshot()["lists"][0]["items"]], ["Leche entera", "pan"])
        for bad in (dict(id=second["id"], text="LECHE ENTERA"), dict(id=second["id"], text="  "), dict(id=999, text="x"), dict(text="x")):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("list_edit", **bad)
        self.assertEqual([i["text"] for i in self.editor.snapshot()["lists"][0]["items"]], ["Leche entera", "pan"])

    def test_list_items_are_marked_not_removed(self):
        self.do("list_add", list="super", text="leche")
        self.do("list_add", list="super", text="pan")
        first, second = self.editor.snapshot()["lists"][0]["items"]
        self.assertEqual((first["done"], second["done"]), (False, False))
        self.assertEqual(self.do("list_check", id=first["id"], done=True), "Marcado.")
        items = self.editor.snapshot()["lists"][0]["items"]
        self.assertEqual([(i["text"], i["done"]) for i in items], [("leche", True), ("pan", False)])  # Sigue en la lista.
        self.assertIn("✓ leche", self.assistant.handle_text("qué hay en la lista del súper").text)
        self.assertEqual(self.do("list_check", id=first["id"], done=False), "Desmarcado.")
        self.assertFalse(self.editor.snapshot()["lists"][0]["items"][0]["done"])
        with self.assertRaises(ApunteError):
            self.do("list_clear_done", list="super")
        self.do("list_check", id=second["id"], done=True)
        self.assertEqual(self.do("list_clear_done", list="super"), "Quité 1 elemento marcado.")
        self.assertEqual([i["text"] for i in self.editor.snapshot()["lists"][0]["items"]], ["leche"])
        for bad in (dict(id=first["id"], done="si"), dict(id=999, done=True), dict(done=True)):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("list_check", **bad)

    def test_habit_card_has_week_record_and_can_be_edited(self):
        self.do("habit_add", title="leer", time="21:00")
        self.do("habit_add", title="correr", time=None)
        habit = self.editor.snapshot()["habits"][0]
        for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-11-08", "2026-11-09"):
            self.store.mark_habit(habit["id"], day)
        self.do("habit_done", id=habit["id"])  # Hoy es martes 10 de noviembre.
        view = self.editor.snapshot()["habits"][0]
        self.assertEqual((view["streak"], view["best"], view["total"]), (3, 3, 6))
        self.assertEqual([d["day"] for d in view["week"]][0], "2026-11-04")
        self.assertEqual([d["done"] for d in view["week"]], [False, False, False, False, True, True, True])
        self.assertEqual(self.do("habit_edit", id=habit["id"], title="  leer un capítulo ", time="22:15"), "Hábito guardado.")
        self.assertEqual((self.store.habits()[0]["title"], self.store.habits()[0]["remind_at"]), ("Leer un capítulo", "22:15"))
        self.do("habit_edit", id=habit["id"], title="Leer un capítulo", time=None)
        self.assertIsNone(self.store.habits()[0]["remind_at"])
        self.assertEqual(self.editor.snapshot()["habits"][0]["total"], 6)  # Editar no toca el historial.
        for bad in (dict(id=habit["id"], title="CORRER"), dict(id=habit["id"], title=" "), dict(id=habit["id"], title="x", time="tarde"),
                    dict(id=999, title="x"), dict(title="x")):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("habit_edit", **bad)

    def test_todays_habit_mark_can_be_undone(self):
        self.do("habit_add", title="leer", time=None)
        habit = self.editor.snapshot()["habits"][0]
        self.store.mark_habit(habit["id"], "2026-11-09")  # Ayer.
        self.do("habit_done", id=habit["id"])
        self.assertEqual([(h["done"], h["streak"]) for h in self.editor.snapshot()["habits"]], [(True, 2)])
        self.assertEqual(self.do("habit_undo", id=habit["id"]), "Desmarqué «Leer» de hoy. Racha: 1 día.")
        self.assertEqual([(h["done"], h["streak"]) for h in self.editor.snapshot()["habits"]], [(False, 1)])  # La de ayer se conserva.
        for bad in (dict(id=habit["id"]), dict(id=999), dict()):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("habit_undo", **bad)

    def test_notes_are_the_memory(self):
        self.do("note_add", text="  la clave del wifi   está en el cajón ")
        notes = self.editor.snapshot()["notes"]
        self.assertEqual([n["text"] for n in notes], ["La clave del wifi está en el cajón"])
        self.do("note_delete", id=notes[0]["id"])
        self.assertEqual(self.editor.snapshot()["notes"], [])
        with self.assertRaises(ApunteError):
            self.do("note_delete", id=notes[0]["id"])

    def test_notes_can_be_corrected_and_stay_searchable(self):
        self.do("note_add", text="mi veterinaria se llama Ana")
        self.do("note_add", text="la clave del wifi está en el cajón")
        second, first = self.editor.snapshot()["notes"]  # La más nueva va primero.
        self.assertEqual(self.do("note_edit", id=first["id"], text="  mi veterinaria se llama   Lucía "), "Nota guardada.")
        self.assertEqual([n["text"] for n in self.editor.snapshot()["notes"]],
                         ["La clave del wifi está en el cajón", "Mi veterinaria se llama Lucía"])
        self.assertEqual([fact for _, fact in self.store.search_facts("veterinaria Lucía", 5)], ["Mi veterinaria se llama Lucía"])
        self.assertEqual(self.store.search_facts("Ana", 5), [])  # El texto viejo ya no aparece al buscar.
        for bad in (dict(id=first["id"], text="LA CLAVE DEL WIFI ESTÁ EN EL CAJÓN"), dict(id=first["id"], text="  "),
                    dict(id=999, text="x"), dict(text="x")):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("note_edit", **bad)
        self.assertEqual(len(self.editor.snapshot()["notes"]), 2)
        self.assertEqual(second["text"], "La clave del wifi está en el cajón")

    def test_habits_and_their_streak(self):
        self.assertIn("08:00", self.do("habit_add", title="tomar agua", time="08:00"))
        self.do("habit_add", title="leer", time=None)
        first, second = self.editor.snapshot()["habits"]
        self.assertEqual((first["title"], first["remind_at"], first["done"], first["streak"]), ("Tomar agua", "08:00", False, 0))
        self.assertIsNone(second["remind_at"])
        self.assertIn("Racha: 1 día", self.do("habit_done", id=first["id"]))
        self.assertEqual([(h["done"], h["streak"]) for h in self.editor.snapshot()["habits"]], [(True, 1), (False, 0)])
        self.do("habit_delete", id=second["id"])
        self.assertEqual(len(self.editor.snapshot()["habits"]), 1)
        with self.assertRaises(ApunteError):
            self.do("habit_add", title="correr", time="mañana")

    def test_dates(self):
        self.assertIn("3 de marzo", self.do("date_add", kind="cumpleaños", name="mi mamá", day=3, month=3, year=1966))
        self.do("date_add", kind="aniversario", name="", day=14, month=2)
        dates = self.editor.snapshot()["dates"]
        self.assertEqual([(d["day"], d["month"], d["label"]) for d in dates],
                         [(14, 2, "tu aniversario"), (3, 3, "cumpleaños de tu mamá")])
        self.do("date_delete", id=dates[0]["id"])
        for bad in (
            dict(kind="cumpleaños", name="Ana", day=31, month=4), dict(kind="cumpleaños", name="", day=1, month=1),
            dict(kind="fiesta", name="Ana", day=1, month=1), dict(kind="cumpleaños", name="Ana", day=1, month=13),
            dict(kind="cumpleaños", name="Ana", day="1", month=1), dict(kind="cumpleaños", name="Ana <b>", day=1, month=1),
            dict(kind="cumpleaños", name="Ana", day=1, month=1, year=3000),
        ):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("date_add", **bad)
        self.assertEqual(len(self.editor.snapshot()["dates"]), 1)

    def test_dates_come_in_order_with_countdown_and_age(self):
        # Hoy es 10 de noviembre de 2026.
        self.do("date_add", kind="cumpleaños", name="mi mamá", day=3, month=3, year=1966)
        self.do("date_add", kind="cumpleaños", name="Ana", day=10, month=11)
        self.do("date_add", kind="aniversario", name="Laura", day=12, month=11, year=2020)
        dates = self.editor.snapshot()["dates"]
        self.assertEqual([(d["name"], d["in_days"], d["next"], d["turns"]) for d in dates], [
            ("Ana", 0, "2026-11-10", None), ("Laura", 2, "2026-11-12", 6), ("mi mamá", 113, "2027-03-03", 61),
        ])

    def test_edit_a_date_keeps_its_note_in_step(self):
        self.do("date_add", kind="cumpleaños", name="Ana", day=3, month=3)
        self.do("date_add", kind="cumpleaños", name="Luis", day=4, month=4)
        ana = next(d for d in self.editor.snapshot()["dates"] if d["name"] == "Ana")
        self.assertEqual(self.do("date_edit", id=ana["id"], kind="cumpleaños", name="Ana María", day=5, month=3, year=1990), "Fecha guardada.")
        edited = next(d for d in self.editor.snapshot()["dates"] if d["id"] == ana["id"])
        self.assertEqual((edited["name"], edited["day"], edited["month"], edited["year"]), ("Ana María", 5, 3, 1990))
        notes = [text for _, text in self.store.list_facts()]
        self.assertIn("Ana María cumple años el 5 de marzo", notes)
        self.assertNotIn("Ana cumple años el 3 de marzo", notes)
        self.assertEqual(self.do("date_edit", id=ana["id"], kind="cumpleaños", name="Ana María", day=5, month=3, year=1990), "Sin cambios.")
        luis = next(d for d in self.editor.snapshot()["dates"] if d["name"] == "Luis")
        for bad in (dict(id=luis["id"], kind="cumpleaños", name="ana maría", day=4, month=4),  # Ya existe.
                    dict(id=luis["id"], kind="cumpleaños", name="Luis", day=30, month=2),
                    dict(id=luis["id"], kind="cumpleaños", name="Luis", day=29, month=2, year=2023),
                    dict(id=999, kind="cumpleaños", name="Luis", day=4, month=4)):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("date_edit", **bad)
        self.do("date_delete", id=ana["id"])
        self.assertNotIn("Ana María cumple años el 5 de marzo", [text for _, text in self.store.list_facts()])

    def test_leap_day_is_celebrated_on_the_28th(self):
        from datetime import date

        from hermes.extras import next_occurrence

        self.assertEqual(next_occurrence(2, 29, date(2026, 11, 10)), date(2027, 2, 28))
        self.assertEqual(next_occurrence(2, 29, date(2027, 11, 10)), date(2028, 2, 29))
        self.do("date_add", kind="cumpleaños", name="Pepe", day=29, month=2)
        self.assertTrue(any("Pepe" in line for line in self.assistant.extras.date_lines(date(2027, 2, 28))))
        self.assertFalse(any("Pepe" in line for line in self.assistant.extras.date_lines(date(2028, 2, 27))))  # En bisiesto, el 28 aún no es (mañana tampoco).

    def test_waiting_and_silence_show_up(self):
        self.assistant.handle_text("estoy esperando que Juan me mande el contrato")
        self.assistant.handle_text("no me molestes hasta las 3")
        snapshot = self.editor.snapshot()
        self.assertEqual([w["title"] for w in snapshot["waiting"]], ["Esperando que Juan me mande el contrato"])
        self.assertEqual(snapshot["quiet_until"], int(datetime(2026, 11, 10, 15, 0, tzinfo=TZ).timestamp()))
        self.do("quiet_off")
        self.assertIsNone(self.editor.snapshot()["quiet_until"])

    def test_followups_are_added_edited_and_deleted_from_the_page(self):
        self.assertEqual(self.do("waiting_add", text="  estoy esperando que Juan mande el contrato ", days=5),
                         "⏳ Anotado: estás esperando que Juan mande el contrato.")
        self.do("waiting_add", text="la factura del taller")
        first, second = sorted(self.editor.snapshot()["waiting"], key=lambda w: w["id"])
        self.assertEqual((first["title"], second["title"]), ("Esperando que Juan mande el contrato", "Esperando la factura del taller"))
        self.assertEqual(first["due_at"], int(datetime(2026, 11, 15, 9, 0, tzinfo=TZ).timestamp()))  # En 5 días, a las 9.
        self.assertEqual(second["due_at"], int(datetime(2026, 11, 13, 9, 0, tzinfo=TZ).timestamp()))  # Por defecto, 3.
        self.store.update_task(first["id"], 0, notified_at=1)
        self.assertEqual(self.do("waiting_edit", id=first["id"], text="Juan: contrato firmado", date="2026-11-20"), "Seguimiento guardado.")
        task = self.store.get_task(first["id"])
        self.assertEqual((task.title, task.due_at, task.notified_at),
                         ("Juan: contrato firmado", int(datetime(2026, 11, 20, 9, 0, tzinfo=TZ).timestamp()), None))
        self.assertEqual(self.do("waiting_edit", id=first["id"], text="Juan: contrato firmado", date="2026-11-20"), "Sin cambios.")
        # Hoy, con la hora por defecto ya pasada: pregunta enseguida en vez de quedar en el pasado.
        self.do("waiting_edit", id=second["id"], text="Esperando la factura del taller", date="2026-11-10")
        self.assertEqual(self.store.get_task(second["id"]).due_at, int(self.moment.timestamp()))
        self.assertIn("Borré el seguimiento", self.do("waiting_delete", id=second["id"]))
        self.assertEqual([w["id"] for w in self.editor.snapshot()["waiting"]], [first["id"]])
        ordinary = self.store.add_task("Tarea normal", "casa", "media", None, "", 0)
        for bad in (dict(action="waiting_add", text="  "), dict(action="waiting_add", text="x", days=0), dict(action="waiting_add", text="x", days="3"),
                    dict(action="waiting_edit", id=first["id"], text=""), dict(action="waiting_edit", id=first["id"], text="x", date="2026-11-09"),
                    dict(action="waiting_edit", id=first["id"], text="x", date="mañana"), dict(action="waiting_edit", id=ordinary.id, text="x"),
                    dict(action="waiting_delete", id=second["id"]), dict(action="waiting_delete", id=ordinary.id)):
            with self.assertRaises(ApunteError, msg=bad):
                self.editor.apply(bad)
        self.assertEqual(self.store.get_task(ordinary.id).status, "pending")

    def test_malformed_requests(self):
        for payload in (None, [], {}, {"action": "borrar_todo"}, {"action": "list_add", "list": "", "text": "x"},
                        {"action": "list_add", "list": "super", "text": 5}, {"action": "list_remove", "id": "1"},
                        {"action": "note_add", "text": "   "}, {"action": "habit_done", "id": True}):
            with self.assertRaises(ValueError, msg=payload):
                self.editor.apply(payload)

    def test_served_by_the_page(self):
        port = free_port()
        status = VoiceStatus()
        status.set_source("extras", self.editor.snapshot)
        status.set_action("extras", self.editor.apply)
        server = start_status_server(status, port)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def call(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(method, path, body=body, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
            response = connection.getresponse()
            data = response.read()
            connection.close()
            return response.status, data

        page = call("GET", "/")[1].decode("utf-8")
        self.assertIn('id="view-apuntes"', page)
        token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)
        headers = {"Origin": f"http://127.0.0.1:{port}", "X-Hermes-Token": token, "Content-Type": "application/json"}
        body = json.dumps({"action": "list_add", "list": "super", "text": "pilas"})
        self.assertEqual(call("POST", "/extras", body, {**headers, "X-Hermes-Token": "x"})[0], 403)
        self.assertEqual(call("POST", "/extras", body, headers)[0], 200)
        status_code, data = call("POST", "/extras", body, headers)
        self.assertEqual((status_code, "ya estaba" in json.loads(data)["error"]), (400, True))
        self.assertEqual(json.loads(call("GET", "/extras")[1])["lists"][0]["items"][0]["text"], "pilas")
