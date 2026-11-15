import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from hermes import spoken
from hermes.claude_cli import HybridLLM
from hermes.llm import SPOKEN_STYLE, reply_messages, web_messages
from hermes.speakers import (
    FallbackSpeaker,
    KokoroSpeaker,
    MicrosoftSpeaker,
    SwitchableSpeaker,
    build_speaker,
    parse_voice,
    split_sentences,
)
from hermes.store import Task
from tests.test_core import TZ, Harness

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=TZ)  # martes


def ts(day, hour, minute=0):
    return int(datetime(2026, 11, day, hour, minute, tzinfo=TZ).timestamp())


def task(title="Pagar la luz", due=None, **fields):
    return Task(1, title, "finanzas", fields.pop("urgency", "media"), due, "pending", None, **fields)


class PhraseTests(unittest.TestCase):
    def test_times_are_said_like_people_say_them(self):
        cases = {
            (10, 15, 0): "hoy a las 3 de la tarde",
            (11, 9, 30): "mañana a las 9 y media de la mañana",
            (12, 13, 15): "pasado mañana a la 1 y cuarto de la tarde",
            (13, 20, 0): "el viernes a las 8 de la noche",
            (20, 12, 0): "el viernes 20 de noviembre a las 12 del mediodía",
            (9, 7, 20): "ayer a las 7:20 de la mañana",
            (11, 0, 30): "mañana a las 12 y media de la madrugada",
        }
        for (day, hour, minute), expected in cases.items():
            self.assertEqual(spoken.spoken_moment(ts(day, hour, minute), NOW), expected)

    def test_intervals(self):
        self.assertEqual(
            [spoken.spoken_interval(m) for m in (15, 30, 60, 120)],
            ["cada 15 minutos", "cada media hora", "cada hora", "cada 2 horas"],
        )

    def test_title_inside_a_sentence(self):
        self.assertEqual(spoken.in_sentence("Pagar la luz."), "pagar la luz")
        self.assertEqual(spoken.in_sentence("IVA de noviembre"), "IVA de noviembre")

    def test_created(self):
        said = spoken.created(task(due=ts(11, 15)), NOW)
        self.assertTrue(said.startswith(spoken.CREATED), said)
        self.assertIn("te recuerdo pagar la luz mañana a las 3 de la tarde.", said)
        for forbidden in ("#", "finanzas", "·", "15:00", "\n"):
            self.assertNotIn(forbidden, said)

    def test_created_variants(self):
        self.assertIn("anoté pagar la luz, sin fecha por ahora.", spoken.created(task(), NOW))
        self.assertIn("anoté pagar la luz; vence el viernes a las 6 de la tarde.",
                      spoken.created(task(deadline_at=ts(13, 18)), NOW))
        full = spoken.created(task(due=ts(11, 9), deadline_at=ts(13, 17), repeat_minutes=30, urgency="alta"), NOW, ["Empacar", "Contratar el camión", "Limpiar"])
        self.assertIn("mañana a las 9 de la mañana, y vence el viernes a las 5 de la tarde.", full)
        self.assertIn("Te lo voy a repetir cada media hora hasta que lo hagas.", full)
        self.assertIn("Le puse 3 pasos: empacar, contratar el camión y limpiar.", full)
        self.assertIn("Quedó como urgente.", full)

    def test_steps_are_named(self):
        self.assertEqual(spoken.step_names(["Empacar"]), "empacar")
        self.assertEqual(spoken.step_names(list("ABCDEF")), "A, B, C, D y 2 más")
        self.assertIn("mudanza, le falta empacar.", spoken.task_list([task(title="Mudanza")], {1: ["Empacar"]}, NOW))
        self.assertIn("le agregué 2 pasos a pagar la luz: llamar y pagar.", spoken.steps_added(task(), ["Llamar", "Pagar"]))

    def test_openers_vary(self):
        openers = {spoken.created(task(), NOW).split(",")[0] for _ in range(60)}
        self.assertGreater(len(openers), 1)

    def test_finished(self):
        said = spoken.finished(task(), "done", ["Quedan 2 de «Mudanza»."])
        self.assertIn("ya marqué como hecho pagar la luz. Quedan 2 de «Mudanza».", said)
        self.assertEqual(spoken.finished(task(), "cancelled", []), "Listo, borré pagar la luz.")

    def test_task_list(self):
        tasks = [
            Task(1, "Pagar la luz", "finanzas", "media", ts(11, 15), "pending", None),
            Task(2, "Mudanza", "casa", "media", None, "pending", None),
            Task(3, "Entregar informe", "trabajo", "media", ts(9, 9), "pending", None),
        ]
        said = spoken.task_list(tasks, {2: ["Empacar", "Contratar el camión"]}, NOW)
        self.assertEqual(
            said,
            "Tienes 3 pendientes: pagar la luz, mañana a las 3 de la tarde; mudanza, le faltan 2 pasos: "
            "empacar y contratar el camión; "
            "y entregar informe, que ya está atrasada.",
        )
        self.assertEqual(spoken.task_list(tasks[:1], {}, NOW), "Tienes un pendiente: pagar la luz, mañana a las 3 de la tarde.")
        self.assertEqual(spoken.task_list([], {}, NOW), "No tienes pendientes. Estás al día.")
        many = [Task(i, f"Tarea {i}", "casa", "media", None, "pending", None) for i in range(1, 9)]
        self.assertTrue(spoken.task_list(many, {}, NOW).endswith("y tarea 5. Y 3 más."))


class AssistantVoiceTests(Harness):
    def test_voice_reply_has_a_spoken_version_and_telegram_text_is_unchanged(self):
        self.llm.next = {"intent": "create_task", "title": "Pagar la luz", "date": "2026-11-11", "time": "15:00",
                         "category": "finanzas", "urgency": "media"}
        reply = self.assistant.handle_text("recuérdame pagar la luz mañana a las 3", spoken=True)
        self.assertIn("te recuerdo pagar la luz mañana a las 3 de la tarde.", reply.spoken)
        self.assertIn("#1 Pagar la luz", reply.text)
        self.assertIn("miércoles 11 nov, 15:00", reply.text)

    def test_list_done_and_edit_are_spoken(self):
        self.say("x", title="Pagar la luz", date="2026-11-11", time="15:00")
        listed = self.say("qué tengo", name="list_tasks")
        self.assertEqual(listed.spoken, "Tienes un pendiente: pagar la luz, mañana a las 3 de la tarde.")
        edited = self.say("ponla urgente", name="edit_task", urgency="alta")
        self.assertIn("ya la cambié: pagar la luz, mañana a las 3 de la tarde. Quedó como urgente.", edited.spoken)
        done = self.say("ya pagué la luz", name="complete_task", task_id=1)
        self.assertIn("ya marqué como hecho pagar la luz.", done.spoken)

    def test_model_gets_the_spoken_style_only_for_voice(self):
        calls = []
        self.llm.reply = lambda *args, **kwargs: calls.append(kwargs) or "hola"
        self.llm.next = {"intent": "chat"}
        self.assistant.handle_text("hola")
        self.assistant.handle_text("hola", spoken=True)
        self.assistant.handle_text("hola")
        self.assertEqual(calls, [{}, {"spoken": True}, {}])


class VoiceCommandTests(Harness):
    def test_shows_current_voice_and_options(self):
        reply = self.assistant.handle_text("/voz")
        self.assertIn("Voz actual: piper", reply.text)
        self.assertIn("/voz microsoft", reply.text)

    def test_choice_is_saved_and_normalized(self):
        reply = self.assistant.handle_text("/voz Microsoft")
        self.assertEqual(self.store.kv_get("voice"), "microsoft:es-MX-DaliaNeural")
        self.assertIn("microsoft:es-MX-DaliaNeural", reply.text)
        self.assistant.handle_text("/voz kokoro:em_alex")
        self.assertEqual(self.store.kv_get("voice"), "kokoro:em_alex")
        self.assertIn("Voz actual: kokoro:em_alex", self.assistant.handle_text("/voz").text)

    def test_unknown_voice_changes_nothing(self):
        reply = self.assistant.handle_text("/voz robot")
        self.assertIn("No conozco esa voz", reply.text)
        self.assertIsNone(self.store.kv_get("voice"))


class PromptTests(unittest.TestCase):
    def test_chat_prompt(self):
        self.assertNotIn(SPOKEN_STYLE, reply_messages("hola", [])[0]["content"])
        self.assertIn(SPOKEN_STYLE, reply_messages("hola", [], spoken=True)[0]["content"])

    def test_web_prompt(self):
        result = SimpleNamespace(title="t", content="c")
        self.assertNotIn(SPOKEN_STYLE, web_messages("q", "b", [result], NOW)[0]["content"])
        system = web_messages("q", "b", [result], NOW, spoken=True)[0]["content"]
        self.assertIn(SPOKEN_STYLE, system)
        self.assertLess(system.index(SPOKEN_STYLE), system.index("Resultados:"))  # El estilo va antes del texto de internet.

    def test_hybrid_passes_the_style_to_claude(self):
        seen = []
        claude = SimpleNamespace(complete=lambda messages, purpose: seen.append(messages[0]["content"]) or "ok")
        HybridLLM(SimpleNamespace(), claude).reply("hola", [], spoken=True)
        self.assertIn(SPOKEN_STYLE, seen[0])


class FakeVoice:
    def __init__(self, error=None):
        self.error, self.said, self.chimes = error, [], 0

    def speak(self, text):
        if self.error:
            raise self.error
        self.said.append(text)

    def chime(self):
        self.chimes += 1


class SpeakerTests(unittest.TestCase):
    def test_parse_voice(self):
        self.assertEqual(parse_voice("piper"), ("piper", ""))
        self.assertEqual(parse_voice(" Microsoft "), ("microsoft", "es-MX-DaliaNeural"))
        self.assertEqual(parse_voice("microsoft:es-MX-JorgeNeural"), ("microsoft", "es-MX-JorgeNeural"))
        self.assertEqual(parse_voice("kokoro:em_alex"), ("kokoro", "em_alex"))
        self.assertEqual(parse_voice(""), ("piper", ""))
        with self.assertLogs("hermes.speakers", level="WARNING"):
            self.assertEqual(parse_voice("otra"), ("piper", ""))
        with self.assertLogs("hermes.speakers", level="WARNING"):
            self.assertEqual(parse_voice("kokoro:../../x y"), ("kokoro", "ef_dora"))

    def test_split_sentences(self):
        self.assertEqual(split_sentences("¡Listo! Te recuerdo pagar. ¿Algo más?"), ["¡Listo!", "Te recuerdo pagar.", "¿Algo más?"])
        self.assertEqual(split_sentences("  "), [])

    def test_fallback_uses_backup_when_primary_fails(self):
        primary, backup = FakeVoice(OSError("sin internet")), FakeVoice()
        speaker = FallbackSpeaker(primary, backup)
        with self.assertLogs("hermes.speakers", level="WARNING"):
            speaker.speak("hola")
        speaker.chime()
        self.assertEqual((backup.said, backup.chimes), (["hola"], 1))

    def test_fallback_prefers_primary(self):
        primary, backup = FakeVoice(), FakeVoice()
        FallbackSpeaker(primary, backup).speak("hola")
        self.assertEqual((primary.said, backup.said), (["hola"], []))

    def test_microsoft_fetches_decodes_and_plays(self):
        played = []
        speaker = MicrosoftSpeaker(
            "es-MX-DaliaNeural",
            fetch=lambda text, voice: f"{voice}|{text}".encode(),
            decode=lambda data: (data, 24000),
            play=lambda samples, rate: played.append((samples, rate)),
        )
        speaker.speak("hola")
        self.assertEqual(played, [(b"es-MX-DaliaNeural|hola", 24000)])

    def test_kokoro_plays_sentence_by_sentence(self):
        played = []
        engine = SimpleNamespace(create=lambda text, voice, speed, lang: ((text, voice, lang), 24000))
        KokoroSpeaker(engine, "ef_dora", play=lambda samples, rate: played.append(samples)).speak("Uno. Dos.")
        self.assertEqual(played, [("Uno.", "ef_dora", "es"), ("Dos.", "ef_dora", "es")])

    def test_kokoro_errors_reach_the_fallback(self):
        def broken(*_, **__):
            raise RuntimeError("modelo")

        backup = FakeVoice()
        speaker = FallbackSpeaker(KokoroSpeaker(SimpleNamespace(create=broken), "ef_dora", play=lambda *_: None), backup)
        with self.assertLogs("hermes.speakers", level="WARNING"):
            speaker.speak("hola")
        self.assertEqual(backup.said, ["hola"])

    def test_switchable_speaker_changes_voice_without_restart(self):
        setting, built = ["piper"], []
        voices = {"piper": FakeVoice(), "kokoro:em_alex": FakeVoice()}

        def build(name, piper, folder):
            built.append(name)
            return voices[name]

        speaker = SwitchableSpeaker(lambda: setting[0], voices["piper"], Path("x"), build)
        speaker.speak("uno")
        speaker.speak("dos")
        setting[0] = "kokoro:em_alex"
        speaker.speak("tres")
        speaker.chime()
        self.assertEqual(built, ["piper", "kokoro:em_alex"])  # Solo prepara la voz cuando cambia.
        self.assertEqual((voices["piper"].said, voices["kokoro:em_alex"].said), (["uno", "dos"], ["tres"]))
        self.assertEqual(voices["piper"].chimes, 1)

    def test_build_defaults_to_piper(self):
        piper = FakeVoice()
        self.assertIs(build_speaker("piper", piper, Path("no-existe")), piper)

    def test_build_without_model_files_falls_back(self):
        piper = FakeVoice()
        with self.assertLogs("hermes.speakers", level="WARNING"):
            self.assertIs(build_speaker("kokoro", piper, Path("no-existe")), piper)


if __name__ == "__main__":
    unittest.main()
