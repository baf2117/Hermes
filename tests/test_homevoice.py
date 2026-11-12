import unittest
from array import array
from types import SimpleNamespace

from hermes.homevoice import (
    FRAME_SAMPLES,
    HomeVoice,
    RecordSettings,
    record_utterance,
    rms,
    speakable,
    strip_wake_word,
    wait_while_paused,
)
import threading

from hermes.status import VoiceStatus
from hermes.voice import is_hallucination

SILENCE = array("h", [0] * FRAME_SAMPLES).tobytes()
SPEECH = array("h", [3000, -3000] * (FRAME_SAMPLES // 2)).tobytes()


def reader(frames):
    iterator = iter(frames)

    def read():
        return next(iterator, SILENCE)

    return read


class HallucinationTests(unittest.TestCase):
    def test_typical_inventions_are_detected(self):
        for text in ("¡Suscríbete!", "Suscríbete al canal.", "Gracias por ver el video.", "Subtítulos realizados por la comunidad"):
            self.assertTrue(is_hallucination(text), text)

    def test_real_orders_are_kept(self):
        for text in ("Recuérdame suscribirme a Netflix", "Suscríbete a Netflix mañana", "Gracias por avisarme", ""):
            self.assertFalse(is_hallucination(text), text)


class SpeakableTests(unittest.TestCase):
    def test_removes_emoji_numbers_and_correction_note(self):
        text = "Listo, la anoté:\n🟡 #12 Pagar la luz\n     finanzas · viernes 13 nov, 09:00\n\nSi algo está mal, dímelo y lo corrijo."
        spoken = speakable(text)
        self.assertEqual(spoken, "Listo, la anoté: Pagar la luz. finanzas , viernes 13 nov, 09:00")

    def test_keeps_accents_and_question_marks(self):
        self.assertEqual(speakable("¿Cómo estás, señor?"), "¿Cómo estás, señor?")

    def test_long_text_is_cut_on_a_word(self):
        spoken = speakable("palabra " * 200)
        self.assertLess(len(spoken), 560)
        self.assertTrue(spoken.endswith("El resto te lo dejo en Telegram."))


class RecordingTests(unittest.TestCase):
    def test_rms(self):
        self.assertEqual(rms(SILENCE), 0)
        self.assertEqual(rms(SPEECH), 3000)

    def test_stops_after_silence_and_starts_with_speech(self):
        settings = RecordSettings(end_silence_frames=3)
        pcm = record_utterance(reader([SILENCE] * 4 + [SPEECH] * 5 + [SILENCE] * 10), 100, settings)
        self.assertEqual(len(pcm), (5 + 3) * len(SPEECH))

    def test_nothing_said_returns_none(self):
        self.assertIsNone(record_utterance(reader([]), 100, RecordSettings(start_timeout_frames=5)))

    def test_short_click_is_not_speech(self):
        settings = RecordSettings(end_silence_frames=3, min_speech_frames=3)
        self.assertIsNone(record_utterance(reader([SPEECH]), 100, settings))

    def test_maximum_length(self):
        pcm = record_utterance(reader([SPEECH] * 500), 100, RecordSettings(max_frames=10))
        self.assertEqual(len(pcm), 10 * len(SPEECH))

    def test_threshold_follows_room_noise(self):
        # Con ruido alto, este nivel no cuenta como voz.
        self.assertIsNone(record_utterance(reader([SPEECH] * 20), 2000, RecordSettings(start_timeout_frames=5)))


class FakeDetector:
    def __init__(self, fires):
        self.fires = list(fires)
        self.resets = 0

    def feed(self, frame):
        return self.fires.pop(0) if self.fires else False

    def reset(self):
        self.resets += 1


class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.chimes = 0

    def chime(self):
        self.chimes += 1

    def speak(self, text):
        self.said.append(text)


class FakeTranscriber:
    def __init__(self, text="", error=None):
        self.text, self.error = text, error
        self.calls = 0

    def transcribe_pcm(self, pcm):
        self.calls += 1
        if self.error:
            raise self.error
        return self.text


class FakeAssistant:
    def __init__(self):
        self.heard = []

    def handle_text(self, text):
        self.heard.append(text)
        return SimpleNamespace(text="🟡 Listo", buttons=[])


class ConversationTests(unittest.TestCase):
    def build(self, fires, transcriber, frames):
        self.speaker, self.assistant, self.flushes = FakeSpeaker(), FakeAssistant(), []
        self.detector = FakeDetector(fires)
        return HomeVoice(
            self.detector, transcriber, self.assistant, self.speaker, reader(frames),
            lambda: self.flushes.append(1),
        )

    def spoken_frames(self):
        return [SILENCE] + [SPEECH] * 5 + [SILENCE] * 20

    def test_full_conversation(self):
        voice = self.build([True], FakeTranscriber("pagar la luz"), self.spoken_frames())
        voice.step()
        self.assertEqual(self.speaker.chimes, 1)
        self.assertEqual(self.assistant.heard, ["pagar la luz"])
        self.assertEqual(self.speaker.said, ["Listo"])
        self.assertEqual(self.detector.resets, 1)
        self.assertEqual(len(self.flushes), 2)  # tras el aviso sonoro y tras responder

    def test_no_transcription_before_wake_word(self):
        transcriber = FakeTranscriber("x")
        voice = self.build([False, False], transcriber, [SPEECH] * 5)
        voice.step()
        voice.step()
        self.assertEqual(transcriber.calls, 0)
        self.assertEqual(self.speaker.chimes, 0)

    def test_false_activation_stays_silent(self):
        transcriber = FakeTranscriber("x")
        voice = self.build([True], transcriber, [SILENCE] * 100)
        voice.step()
        self.assertEqual(transcriber.calls, 0)
        self.assertEqual(self.assistant.heard, [])
        self.assertEqual(self.speaker.said, [])
        self.assertEqual(self.detector.resets, 1)

    def test_empty_transcription_stays_silent(self):
        voice = self.build([True], FakeTranscriber(""), self.spoken_frames())
        voice.step()
        self.assertEqual(self.assistant.heard, [])
        self.assertEqual(self.speaker.said, [])

    def test_error_apologizes_and_recovers(self):
        voice = self.build([True], FakeTranscriber(error=RuntimeError("x")), self.spoken_frames())
        with self.assertLogs("hermes.homevoice", level="ERROR"):
            voice.step()
        self.assertIn("Perdón", self.speaker.said[0])
        self.assertEqual(self.detector.resets, 1)

    def test_speaker_failure_does_not_escape(self):
        voice = self.build([True], FakeTranscriber("hola"), self.spoken_frames())

        def broken(_):
            raise OSError("sin bocinas")

        self.speaker.speak = broken
        with self.assertLogs("hermes.homevoice", level="ERROR"):
            voice.step()

    def test_wake_word_in_transcript_is_removed_from_the_order(self):
        voice = self.build([True], FakeTranscriber("Hermes, sacar la basura"), self.spoken_frames())
        voice.step()
        self.assertEqual(self.assistant.heard, ["sacar la basura"])

    def test_only_the_name_does_not_reach_the_assistant(self):
        voice = self.build([True], FakeTranscriber("Hermes."), self.spoken_frames())
        voice.step()
        self.assertEqual(self.assistant.heard, [])
        self.assertEqual(self.speaker.said, [])
        self.assertEqual(voice.status.snapshot()["events"][0]["outcome"], "solo_nombre")

    def test_word_containing_the_name_is_kept(self):
        self.assertEqual(strip_wake_word("Hermesito ven", "hermes"), "Hermesito ven")

    def test_status_records_a_full_conversation(self):
        voice = self.build([True], FakeTranscriber("pagar la luz"), self.spoken_frames())
        voice.step()
        snapshot = voice.status.snapshot()
        event = snapshot["events"][0]
        self.assertEqual(snapshot["state"], "escuchando")
        self.assertEqual(event["outcome"], "ok")
        self.assertEqual((event["heard"], event["reply"]), ("pagar la luz", "Listo"))
        self.assertEqual(set(event["timings"]), {"grabar", "transcribir", "pensar", "hablar", "total"})
        self.assertEqual(event["peak"], 3000)

    def test_status_explains_no_voice_detected(self):
        voice = self.build([True], FakeTranscriber("x"), [SILENCE] * 100)
        voice.step()
        event = voice.status.snapshot()["events"][0]
        self.assertEqual(event["outcome"], "sin_voz")
        self.assertEqual(event["peak"], 0)

    def test_status_records_errors(self):
        voice = self.build([True], FakeTranscriber(error=RuntimeError("x")), self.spoken_frames())
        with self.assertLogs("hermes.homevoice", level="ERROR"):
            voice.step()
        snapshot = voice.status.snapshot()
        self.assertEqual(snapshot["events"][0]["outcome"], "error")
        self.assertEqual(snapshot["state"], "escuchando")

    def test_noise_floor_adapts_only_when_listening(self):
        voice = self.build([False] * 400, FakeTranscriber(), [SPEECH] * 400)
        start = voice.noise
        for _ in range(400):
            voice.step()
        self.assertGreater(voice.noise, start)


class PauseLoopTests(unittest.TestCase):
    def test_waits_while_paused_and_resumes_listening(self):
        status, stop = VoiceStatus(), threading.Event()
        status.set_paused(True)
        states = []
        stop.wait = lambda _seconds: (states.append(status.snapshot()["state"]), status.set_paused(False))
        wait_while_paused(status, stop)
        self.assertEqual(states, ["pausada"])
        self.assertEqual(status.snapshot()["state"], "escuchando")

    def test_returns_at_once_when_not_paused(self):
        status = VoiceStatus()
        status.set_state("escuchando")
        wait_while_paused(status, threading.Event())
        self.assertEqual(status.snapshot()["state"], "escuchando")

    def test_stop_ends_the_pause(self):
        status, stop = VoiceStatus(), threading.Event()
        status.set_paused(True)
        stop.set()
        wait_while_paused(status, stop)
        self.assertTrue(status.paused)


if __name__ == "__main__":
    unittest.main()
