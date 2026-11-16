import base64
import http.client
import io
import json
import re
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from hermes.pagevoice import BUSY, MAX_SECONDS, NOTHING_HEARD, TOO_LONG, UNAVAILABLE, UNREADABLE, PageVoice, VoiceRenderer
from hermes.remote import RemoteAccess
from hermes.status import MAX_AUDIO_BYTES, VoiceStatus, start_status_server
from hermes.voice import AudioTooLong
from tests.test_status import free_port


class Transcriber:
    def __init__(self, text="recuérdame pagar la luz", error=None):
        self.text, self.error = text, error
        self.seen: list[tuple[bytes, int | None]] = []
        self.paths: list[Path] = []

    def transcribe(self, path, max_seconds=None):
        self.paths.append(path)
        self.seen.append((path.read_bytes(), max_seconds))
        if self.error:
            raise self.error
        return self.text


class Assistant:
    def __init__(self):
        self.orders: list[tuple[str, bool]] = []

    def handle_text(self, text, sent_at=None, spoken=False):
        self.orders.append((text, spoken))
        return SimpleNamespace(text="Listo, la anoté:\n#7 Pagar la luz", spoken="Listo, pagar la luz.", buttons=[])


class PageVoiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.tmp = Path(self.folder.name) / "tmp"
        self.transcriber = Transcriber()
        self.assistant = Assistant()
        self.status = VoiceStatus()
        self.spoken: list[str] = []

    def voice(self, render="default", transcriber="default"):
        def default_render(text):
            self.spoken.append(text)
            return b"AUDIO", "audio/wav"

        return PageVoice(
            self.transcriber if transcriber == "default" else transcriber,
            self.assistant,
            self.tmp,
            default_render if render == "default" else render,
            self.status,
        )

    def test_order_is_transcribed_answered_and_spoken(self):
        result = self.voice().handle(b"grabacion")
        self.assertEqual(result["heard"], "recuérdame pagar la luz")
        self.assertEqual(result["reply"], "Listo, la anoté:\n#7 Pagar la luz")
        self.assertEqual((base64.b64decode(result["audio"]), result["mime"]), (b"AUDIO", "audio/wav"))
        self.assertEqual(self.assistant.orders, [("recuérdame pagar la luz", True)])
        self.assertEqual(self.spoken, ["Listo, pagar la luz."])  # Se dice la versión hablada, no la escrita.
        self.assertEqual(self.transcriber.seen, [(b"grabacion", MAX_SECONDS)])
        event = self.status.snapshot()["events"][0]
        self.assertEqual((event["outcome"], event["heard"], event["reply"]), ("ok", result["heard"], "Listo, pagar la luz."))

    def test_audio_is_never_kept(self):
        self.voice().handle(b"grabacion")
        self.transcriber.error = RuntimeError("roto")
        with self.assertRaises(ValueError):
            self.voice().handle(b"otra")
        self.assertEqual(len(self.transcriber.paths), 2)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_problems_become_messages_for_the_user(self):
        for error, text, message in (
            (None, "", NOTHING_HEARD),
            (AudioTooLong("largo"), "x", TOO_LONG),
            (RuntimeError("formato desconocido"), "x", UNREADABLE),
        ):
            self.transcriber.error, self.transcriber.text = error, text
            with self.assertRaises(ValueError) as caught:
                self.voice().handle(b"grabacion")
            self.assertEqual(str(caught.exception), message)
        self.assertEqual(self.assistant.orders, [])
        with self.assertRaises(ValueError) as caught:
            self.voice(transcriber=None).handle(b"grabacion")
        self.assertEqual(str(caught.exception), UNAVAILABLE)

    def test_reply_arrives_written_when_voice_fails(self):
        def broken(text):
            raise RuntimeError("sin voz")

        for render in (broken, None, lambda text: None):
            result = self.voice(render=render).handle(b"grabacion")
            self.assertEqual(result["reply"], "Listo, la anoté:\n#7 Pagar la luz")
            self.assertNotIn("audio", result)

    def test_one_order_at_a_time(self):
        entered, release = threading.Event(), threading.Event()

        def slow(text):
            entered.set()
            release.wait(5)
            return None

        voice = self.voice(render=slow)
        first = threading.Thread(target=voice.handle, args=(b"grabacion",))
        first.start()
        self.assertTrue(entered.wait(5))
        with self.assertRaises(ValueError) as caught:
            voice.handle(b"otra")
        self.assertEqual(str(caught.exception), BUSY)
        release.set()
        first.join(5)
        self.assertEqual(voice.handle(b"tercera")["heard"], "recuérdame pagar la luz")


class Piper:
    def synthesize(self, text):
        return b"\x01\x00" * 100, 22050


class VoiceRendererTests(unittest.TestCase):
    def test_local_voice_becomes_a_wav(self):
        data, mime = VoiceRenderer(lambda: "piper", Piper)("hola")
        self.assertEqual(mime, "audio/wav")
        with wave.open(io.BytesIO(data)) as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()), (1, 2, 22050, 100))

    def test_microsoft_voice_is_sent_as_received(self):
        asked = []

        def fetch(text, voice):
            asked.append((text, voice))
            return b"MP3"

        self.assertEqual(VoiceRenderer(lambda: "microsoft:es-MX-DaliaNeural", Piper, fetch)("hola"), (b"MP3", "audio/mpeg"))
        self.assertEqual(asked, [("hola", "es-MX-DaliaNeural")])

    def test_falls_back_to_local_voice(self):
        def offline(text, voice):
            raise OSError("sin internet")

        self.assertEqual(VoiceRenderer(lambda: "microsoft:es-MX-DaliaNeural", Piper, offline)("hola")[1], "audio/wav")
        # Kokoro no se carga otra vez para la página: responde la voz local.
        self.assertEqual(VoiceRenderer(lambda: "kokoro:ef_dora", Piper)("hola")[1], "audio/wav")

    def test_no_voice_means_no_audio(self):
        self.assertIsNone(VoiceRenderer(lambda: "piper", lambda: None)("hola"))
        self.assertIsNone(VoiceRenderer(lambda: "piper", Piper)(""))


HOST = "hermes-prueba.example"
PASSWORD = "clave-de-prueba-larga"


class SpeakServerTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.status = VoiceStatus()
        self.received: list[bytes] = []
        self.server = start_status_server(self.status, self.port, RemoteAccess(HOST, PASSWORD))
        page = self.request("GET", "/")[1].decode("utf-8")
        self.token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def enable(self, action=None):
        def default(audio):
            self.received.append(audio)
            return {"heard": "hola", "reply": "Hola."}

        self.status.set_action("speak", action or default)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def speak(self, body=b"grabacion", **overrides):
        headers = {"Origin": f"http://127.0.0.1:{self.port}", "X-Hermes-Token": self.token, "Content-Type": "audio/webm", **overrides}
        return self.request("POST", "/speak", body, headers)

    def test_button_is_offered_only_when_voice_is_available(self):
        self.assertFalse(json.loads(self.request("GET", "/status")[1])["speak"])
        self.assertEqual(self.speak()[0].status, 404)
        self.enable()
        self.assertTrue(json.loads(self.request("GET", "/status")[1])["speak"])

    def test_recording_reaches_hermes_and_the_answer_comes_back(self):
        self.enable()
        response, body = self.speak(b"\x00\x01grabacion")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body), {"heard": "hola", "reply": "Hola."})
        self.assertEqual(self.received, [b"\x00\x01grabacion"])

    def test_needs_origin_and_token_like_any_other_change(self):
        self.enable()
        for overrides in ({"Origin": "https://malicioso.example"}, {"X-Hermes-Token": "adivinado"}, {"Host": "malicioso.example"}):
            self.assertEqual(self.speak(**overrides)[0].status, 403, overrides)
        self.assertEqual(self.received, [])

    def test_only_audio_of_a_reasonable_size(self):
        self.enable()
        self.assertEqual(self.speak(**{"Content-Type": "application/json"})[0].status, 400)
        self.assertEqual(self.speak(b"")[0].status, 400)
        # Se rechaza por el tamaño anunciado, sin llegar a leer el cuerpo.
        self.assertEqual(self.speak(b"x", **{"Content-Length": str(MAX_AUDIO_BYTES + 1)})[0].status, 400)
        self.assertEqual(self.received, [])

    def test_messages_for_the_user_come_back_as_errors(self):
        def nothing(audio):
            raise ValueError(NOTHING_HEARD)

        self.enable(nothing)
        response, body = self.speak()
        self.assertEqual((response.status, json.loads(body)), (400, {"error": NOTHING_HEARD}))

    def test_from_outside_it_needs_the_session(self):
        self.enable()
        outside = {"Host": HOST, "X-Forwarded-For": "203.0.113.9", "Origin": f"https://{HOST}"}
        self.assertEqual(self.speak(**outside)[0].status, 401)
        login = self.request(
            "POST", "/login", f"password={PASSWORD}", {**outside, "Content-Type": "application/x-www-form-urlencoded"}
        )[0]
        cookie = login.getheader("Set-Cookie").split(";")[0]
        self.assertEqual(self.speak(**outside, Cookie=cookie)[0].status, 200)
        self.assertEqual(self.received, [b"grabacion"])


if __name__ == "__main__":
    unittest.main()
