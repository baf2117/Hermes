import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from hermes.assistant import Assistant
from hermes.config import DEFAULT_CATEGORIES, Config
from hermes.llm import LLMError
from hermes.scheduler import Scheduler
from hermes.store import Store
from hermes.telegram import TelegramBot

TZ = timezone(timedelta(hours=-6))
OWNER = 111


def intent(name, **fields):
    data = dict.fromkeys(("title", "date", "time", "relative_minutes", "category", "urgency", "task_id"))
    data.update(intent=name, **fields)
    return data


class FakeLLM:
    def __init__(self):
        self.next = None
        self.fail = False

    def interpret(self, *_):
        if self.fail:
            raise LLMError("caído")
        return self.next

    def reply(self, *_):
        return "hola"


class FakeTranscriber:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error

    def transcribe(self, path):
        if self.error:
            raise self.error
        return self.text


class Harness(unittest.TestCase):
    def setUp(self):
        self.moment = datetime(2026, 11, 10, 10, 0, tzinfo=TZ)  # martes
        self.config = Config(
            telegram_token="x", allowed_chat_id=OWNER, ollama_url="", ollama_model="",
            db_path=":memory:", log_path="", summary_time=time(7, 30),
            default_task_time=time(9, 0), categories=DEFAULT_CATEGORIES,
        )
        self.store = Store(":memory:")
        self.llm = FakeLLM()
        self.assistant = Assistant(self.store, self.llm, self.config, now=lambda: self.moment)
        self.sent = []
        self.send_fails = False
        self.scheduler = Scheduler(self.store, self.assistant, self.config, self._send, now=lambda: self.moment)
        self.store.kv_set("last_summary_date", "2026-11-10")

    def _send(self, text, buttons):
        if self.send_fails:
            raise OSError("sin red")
        self.sent.append(text)

    def say(self, text, **fields):
        self.llm.next = intent(fields.pop("name", "create_task"), **fields)
        return self.assistant.handle_text(text)


class TaskTests(Harness):
    def test_create_with_date_and_time(self):
        reply = self.say("x", title="Pagar", date="2026-11-13", time="15:00", category="finanzas", urgency="alta")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.category, task.urgency), ("finanzas", "alta"))
        self.assertEqual(task.due_at, int(datetime(2026, 11, 13, 15, 0, tzinfo=TZ).timestamp()))
        self.assertIn("viernes 13 nov, 15:00", reply.text)

    def test_invalid_category_and_urgency_fall_back(self):
        self.say("x", title="A", category="inventada", urgency="extrema")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.category, task.urgency), ("personal", "media"))

    def test_relative_minutes(self):
        self.say("x", title="A", relative_minutes=20)
        self.assertEqual(self.store.pending_tasks()[0].due_at, int((self.moment + timedelta(minutes=20)).timestamp()))

    def test_past_datetime_saved_without_reminder(self):
        reply = self.say("x", title="A", date="2026-11-09", time="10:00")
        self.assertIsNone(self.store.pending_tasks()[0].due_at)
        self.assertIn("ya pasó", reply.text)

    def test_garbage_date_saved_without_reminder(self):
        self.say("x", title="A", date="el viernes", time="tarde")
        self.assertIsNone(self.store.pending_tasks()[0].due_at)

    def test_time_only_rolls_to_tomorrow_when_passed(self):
        self.say("x", title="A", time="08:00")
        self.assertEqual(self.store.pending_tasks()[0].due_at, int(datetime(2026, 11, 11, 8, 0, tzinfo=TZ).timestamp()))

    def test_date_only_today_after_default_time(self):
        self.say("hoy", title="A", date="2026-11-10")
        self.assertEqual(self.store.pending_tasks()[0].due_at, int((self.moment + timedelta(hours=1)).timestamp()))

    def test_invented_date_is_dropped_when_message_mentions_no_time(self):
        self.say("comprar grillos para los geckos", title="Comprar grillos", date="2026-11-10")
        self.assertIsNone(self.store.pending_tasks()[0].due_at)

    def test_date_is_kept_when_message_mentions_a_day(self):
        self.say("pagar el viernes", title="Pagar", date="2026-11-13")
        self.assertIsNotNone(self.store.pending_tasks()[0].due_at)

    def test_edit_applies_only_to_last_task_and_only_changed_fields(self):
        self.say("x", title="Primera", category="casa")
        self.say("x", title="Segunda", category="casa", date="2026-11-13", time="09:00")
        self.say("mejor trabajo", name="edit_task", category="trabajo")
        by_title = {t.title: t for t in self.store.pending_tasks()}
        self.assertEqual(by_title["Primera"].category, "casa")
        self.assertEqual(by_title["Segunda"].category, "trabajo")
        self.assertIsNotNone(by_title["Segunda"].due_at)

    def test_edit_failed_date_leaves_task_unchanged(self):
        self.say("x", title="A", date="2026-11-13", time="09:00")
        before = self.store.pending_tasks()[0].due_at
        reply = self.say("x", name="edit_task", date="2026-01-01", time="09:00")
        self.assertEqual(self.store.pending_tasks()[0].due_at, before)
        self.assertIn("No la cambié", reply.text)

    def test_complete_requires_a_valid_pending_id(self):
        self.say("x", title="A")
        self.say("ya", name="complete_task", task_id=None)
        self.say("ya", name="complete_task", task_id=999)
        self.assertEqual(len(self.store.pending_tasks()), 1)
        task_id = self.store.pending_tasks()[0].id
        self.say("ya", name="complete_task", task_id=task_id)
        self.assertEqual(self.store.pending_tasks(), [])

    def test_llm_down_keeps_the_message_as_a_task(self):
        self.llm.fail = True
        reply = self.assistant.handle_text("comprar sustrato")
        self.assertEqual(self.store.pending_tasks()[0].title, "comprar sustrato")
        self.assertIn("no respondió", reply.text)

    def test_chat_does_not_create_tasks(self):
        self.say("hola", name="chat")
        self.assertEqual(self.store.pending_tasks(), [])

    def test_commands(self):
        self.say("x", title="A")
        task_id = self.store.pending_tasks()[0].id
        self.assertIn("A", self.assistant.handle_text("/tareas").text)
        self.assertIn("número", self.assistant.handle_text("/hecho").text)
        self.assistant.handle_text(f"/borrar {task_id}")
        self.assertEqual(self.store.pending_tasks(), [])

    def test_messages_are_logged(self):
        self.say("hola", name="chat")
        self.assertEqual(self.store.recent_messages(5), [("user", "hola"), ("hermes", "hola")])


class ReminderTests(Harness):
    def advance(self, **delta):
        self.moment += timedelta(**delta)

    def test_fires_once(self):
        self.say("x", title="Luz", relative_minutes=5)
        self.scheduler.tick()
        self.assertEqual(self.sent, [])
        self.advance(minutes=5)
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("Atrasado", self.sent[0])

    def test_failed_send_is_retried(self):
        self.say("x", title="Luz", relative_minutes=5)
        self.advance(minutes=5)
        self.send_fails = True
        self.scheduler.tick()
        self.send_fails = False
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)

    def test_late_reminder_after_downtime_is_marked(self):
        self.say("x", title="Luz", relative_minutes=5)
        self.advance(hours=8)
        self.scheduler.tick()
        self.assertIn("Atrasado", self.sent[0])

    def test_done_task_does_not_fire(self):
        self.say("x", title="Luz", relative_minutes=5)
        self.assistant.handle_text(f"/hecho {self.store.pending_tasks()[0].id}")
        self.advance(minutes=10)
        self.scheduler.tick()
        self.assertEqual(self.sent, [])

    def test_snooze_fires_again(self):
        self.say("x", title="Luz", relative_minutes=5)
        self.advance(minutes=5)
        self.scheduler.tick()
        self.assistant.handle_button(f"snooze:{self.store.pending_tasks()[0].id}")
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)
        self.advance(hours=1)
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 2)

    def test_tomorrow_button(self):
        self.say("x", title="Luz", relative_minutes=5)
        self.assistant.handle_button(f"tomorrow:{self.store.pending_tasks()[0].id}")
        self.assertEqual(self.store.pending_tasks()[0].due_at, int(datetime(2026, 11, 11, 9, 0, tzinfo=TZ).timestamp()))

    def test_button_on_finished_task(self):
        self.say("x", title="Luz")
        task_id = self.store.pending_tasks()[0].id
        self.assistant.handle_button(f"done:{task_id}")
        self.assertIn("ya no está", self.assistant.handle_button(f"done:{task_id}").text)

    def test_summary_once_per_day_with_catch_up(self):
        self.store.kv_set("last_summary_date", "2026-11-09")
        self.moment = datetime(2026, 11, 10, 7, 0, tzinfo=TZ)
        self.scheduler.tick()
        self.assertEqual(self.sent, [])
        self.moment = datetime(2026, 11, 10, 12, 0, tzinfo=TZ)  # arranca tarde
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("martes 10 nov", self.sent[0])

    def test_summary_groups_overdue_today_and_urgent(self):
        self.say("x", title="Hoy", date="2026-11-10", time="18:00")
        self.say("x", title="Urgente", urgency="alta")
        self.say("x", title="Luego", date="2026-11-20", time="18:00")
        summary = self.assistant.build_summary()
        self.assertIn("Hoy", summary)
        self.assertIn("Urgente", summary)
        self.assertNotIn("Luego", summary)


class SendTimeTests(Harness):
    def test_message_read_late_still_counts_from_send_time(self):
        self.llm.next = intent("create_task", title="A", relative_minutes=20)
        sent = self.moment - timedelta(hours=2)
        self.assistant.handle_text("x", sent)
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Atrasado", self.sent[0])

    def test_time_valid_when_sent_is_not_rejected_when_read_late(self):
        self.llm.next = intent("create_task", title="A", date="2026-11-10", time="09:30")
        reply = self.assistant.handle_text("x", self.moment - timedelta(hours=2))
        self.assertNotIn("ya pasó", reply.text)
        self.assertIsNotNone(self.store.pending_tasks()[0].due_at)

    def test_future_send_time_is_clamped_to_now(self):
        self.llm.next = intent("create_task", title="A", relative_minutes=20)
        self.assistant.handle_text("x", self.moment + timedelta(days=1))
        self.assertEqual(self.store.pending_tasks()[0].due_at, int((self.moment + timedelta(minutes=20)).timestamp()))


class MemoryTests(Harness):
    def test_remember_and_list_and_forget(self):
        reply = self.say("mi contador es Luis", name="remember_fact", title="Mi contador es Luis")
        self.assertIn("Lo recordaré", reply.text)
        self.assertEqual(self.store.pending_tasks(), [])
        self.assertIn("Luis", self.assistant.handle_text("/memoria").text)
        fact_id = self.store.list_facts()[0][0]
        self.assistant.handle_text(f"/olvidar {fact_id}")
        self.assertEqual(self.store.list_facts(), [])
        self.assertEqual(self.store.search_facts("contador", 5), [])

    def test_forget_button(self):
        self.say("x", name="remember_fact", title="Dato")
        self.assistant.handle_button(f"forget:{self.store.list_facts()[0][0]}")
        self.assertEqual(self.store.list_facts(), [])

    def test_duplicate_fact_is_not_stored_twice(self):
        self.say("x", name="remember_fact", title="Mi gecko es Rocky")
        self.say("x", name="remember_fact", title="mi gecko es rocky")
        self.assertEqual(len(self.store.list_facts()), 1)

    def test_search_ignores_accents_and_stopwords(self):
        self.store.add_fact("El veterinario atendió a Rocky en León", 1)
        self.assertEqual(len(self.store.search_facts("cuándo atendio leon", 5)), 1)
        self.assertEqual(self.store.search_facts("qué es lo que", 5), [])

    def test_search_survives_fts_operators_in_user_text(self):
        for text in ('AND OR NOT "', "a* (b) NEAR", "col:valor -x ^y", "'; DROP TABLE facts; --"):
            self.store.search_facts(text, 5)
            self.store.search_messages(text, 5, 0)

    def test_chat_receives_relevant_memory(self):
        self.store.add_fact("Mi contador se llama Luis", 1)
        seen = []
        self.llm.reply = lambda text, history, memory: seen.append(memory) or "Luis"
        self.say("cómo se llama mi contador", name="chat")
        self.assertIn("Luis", seen[0])

    def test_chat_finds_older_conversation_but_not_recent_duplicates(self):
        self.say("x", name="chat")
        self.store.log_message("user", "compré un termostato nuevo", 100)
        for i in range(8):
            self.store.log_message("user", f"relleno {i}", 200 + i)
        found = self.store.search_messages("termostato", 3, 6)
        self.assertEqual([text for _, text in found], ["compré un termostato nuevo"])
        self.assertEqual(self.store.search_messages("relleno", 10, 6), [(200, "relleno 0"), (201, "relleno 1")])

    def test_commands_are_not_searchable(self):
        self.store.log_message("user", "/olvidar termostato", 1)
        for i in range(7):
            self.store.log_message("hermes", "x", 2 + i)
        self.assertEqual(self.store.search_messages("termostato", 3, 6), [])

    def test_existing_messages_are_indexed_on_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
                " role TEXT NOT NULL, text TEXT NOT NULL);"
                "INSERT INTO messages (ts, role, text) VALUES (1, 'user', 'mensaje antiguo');"
            )
            conn.close()
            store = Store(path)
            self.assertEqual(store.search_messages("antiguo", 3, 0), [(1, "mensaje antiguo")])
            store._conn.close()


class FakeClient:
    def __init__(self):
        self.sent = []
        self.updates = []
        self.downloads = 0

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text))

    def send_typing(self, _):
        pass

    def download_file(self, _, destination):
        self.downloads += 1
        destination.write_bytes(b"audio")

    def answer_button(self, _):
        pass

    def clear_buttons(self, *_):
        pass

    def get_updates(self, offset):
        return self.updates


class TelegramTests(Harness):
    def setUp(self):
        super().setUp()
        self.client = FakeClient()
        self.bot = TelegramBot(self.client, self.assistant, self.store, OWNER)
        self.llm.next = intent("create_task", title="A")

    @staticmethod
    def message(user, chat=None, chat_type="private", **extra):
        return {"message": {"from": {"id": user}, "chat": {"id": chat or user, "type": chat_type}, **extra}}

    def test_owner_creates_task(self):
        self.bot.handle_update(self.message(OWNER, text="hola"))
        self.assertEqual(len(self.store.pending_tasks()), 1)

    def test_stranger_is_ignored(self):
        self.bot.handle_update(self.message(999, text="hola"))
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.store.pending_tasks(), [])

    def test_group_is_ignored_even_for_owner(self):
        self.bot.handle_update(self.message(OWNER, chat=OWNER, chat_type="group", text="hola"))
        self.assertEqual(self.store.pending_tasks(), [])

    def test_stranger_button_is_ignored(self):
        self.say("x", title="A")
        task_id = self.store.pending_tasks()[0].id
        self.bot.handle_update({"callback_query": {
            "id": "1", "from": {"id": 999}, "data": f"done:{task_id}",
            "message": {"message_id": 1, "chat": {"id": 999, "type": "private"}},
        }})
        self.assertEqual(len(self.store.pending_tasks()), 1)

    def test_voice_without_transcriber_is_declined(self):
        self.bot.handle_update(self.message(OWNER, voice={"file_id": "a"}))
        self.assertIn("no están disponibles", self.client.sent[0][1])

    def voice_bot(self, tmp, transcriber):
        return TelegramBot(self.client, self.assistant, self.store, OWNER, transcriber, Path(tmp))

    def test_voice_note_becomes_a_task_and_audio_is_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self.voice_bot(tmp, FakeTranscriber("pagar la luz"))
            bot.handle_update(self.message(OWNER, voice={"file_id": "a", "duration": 3}))
            self.assertEqual(os.listdir(tmp), [])
        self.assertEqual(self.store.pending_tasks()[0].title, "A")
        self.assertIn("Entendí: «pagar la luz»", self.client.sent[0][1])

    def test_failed_transcription_is_reported_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self.voice_bot(tmp, FakeTranscriber(error=RuntimeError("roto")))
            with self.assertLogs("hermes.telegram", level="WARNING"):
                bot.handle_update(self.message(OWNER, voice={"file_id": "a", "duration": 3}))
            self.assertEqual(os.listdir(tmp), [])
        self.assertIn("No pude procesar", self.client.sent[0][1])
        self.assertEqual(self.store.pending_tasks(), [])

    def test_silent_audio_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.voice_bot(tmp, FakeTranscriber("")).handle_update(
                self.message(OWNER, voice={"file_id": "a", "duration": 3})
            )
        self.assertEqual(self.store.pending_tasks(), [])

    def test_long_audio_is_rejected_before_download(self):
        transcriber = FakeTranscriber("x")
        with tempfile.TemporaryDirectory() as tmp:
            self.voice_bot(tmp, transcriber).handle_update(
                self.message(OWNER, voice={"file_id": "a", "duration": 900})
            )
        self.assertEqual(self.client.downloads, 0)

    def test_stranger_voice_is_not_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.voice_bot(tmp, FakeTranscriber("x")).handle_update(
                self.message(999, voice={"file_id": "a", "duration": 3})
            )
        self.assertEqual(self.client.downloads, 0)
        self.assertEqual(self.store.pending_tasks(), [])

    def test_uses_real_send_time_of_message(self):
        self.llm.next = intent("create_task", title="A", relative_minutes=20)
        sent = self.moment - timedelta(hours=2)
        self.bot.handle_update(self.message(OWNER, text="en 20 minutos", date=int(sent.timestamp())))
        self.assertEqual(self.store.pending_tasks()[0].due_at, int((sent + timedelta(minutes=20)).timestamp()))

    def test_pairing_mode_only_reveals_chat_id(self):
        bot = TelegramBot(self.client, self.assistant, self.store, None)
        bot.handle_update(self.message(555, text="recuérdame algo"))
        self.assertEqual(self.client.sent, [(555, "Tu número de chat es: 555")])
        self.assertEqual(self.store.pending_tasks(), [])

    def test_offset_advances_even_if_handler_crashes(self):
        self.client.updates = [{"update_id": 7, **self.message(OWNER, text="hola")}]
        self.assistant.handle_text = lambda *_: 1 / 0
        with self.assertLogs("hermes.telegram", level="ERROR"):
            self.bot.poll_once()
        self.assertEqual(self.store.kv_get("telegram_offset"), "8")


if __name__ == "__main__":
    unittest.main()
