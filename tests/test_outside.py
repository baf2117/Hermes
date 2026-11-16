"""Clima, calendario y vigilante externo: todo con respuestas simuladas, sin salir a internet."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

from hermes.gmail import GmailAuthError
from hermes.outside import (
    Agenda, CalendarClient, Event, Weather, calendar_token_path, find_calendars, run_heartbeat, valid_heartbeat,
)
from hermes.store import Store
from tests.test_core import TZ, Harness

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=TZ)


def forecast(high, low, rain):
    def fetch(url):
        fetch.urls.append(url)
        return json.dumps(
            {"daily": {"temperature_2m_max": [high], "temperature_2m_min": [low], "precipitation_probability_max": [rain]}}
        ).encode("utf-8")

    fetch.urls = []
    return fetch


class WeatherTests(unittest.TestCase):
    def test_only_speaks_up_when_there_is_something_to_say(self):
        for values, expected in (
            ((24.4, 16.2, 80), "🌧 Hoy es probable que llueva (80 %). Entre 16 y 24 °C."),
            ((34.6, 20, 10), "🥵 Hoy hará calor: hasta 35 °C."),
            ((18, 5.2, None), "🥶 Hoy hará frío: mínima de 5 °C."),
            ((25, 15, 20), ""),
        ):
            self.assertEqual(Weather((14.6, -90.5), forecast(*values)).line(), expected)

    def test_sends_only_the_coordinates(self):
        fetch = forecast(25, 15, 0)
        Weather((14.6, -90.5), fetch).line()
        self.assertTrue(fetch.urls[0].startswith("https://api.open-meteo.com/v1/forecast?latitude=14.6&longitude=-90.5&"))

    def test_bad_answers_raise_instead_of_inventing(self):
        with self.assertRaises(RuntimeError):
            Weather((0, 0), lambda url: b"{}").line()

        def offline(url):
            raise OSError("sin red")

        with self.assertRaises(RuntimeError):
            Weather((0, 0), offline).line()


class SummaryExtrasTests(Harness):
    def test_weather_and_agenda_join_the_morning_summary(self):
        self.assistant.weather = lambda: "🌧 Hoy es probable que llueva (80 %). Entre 16 y 24 °C."
        self.assistant.agenda = lambda now: ["09:00 Junta", "Todo el día: Feriado"]
        summary = self.assistant.build_summary()
        self.assertIn("🌧 Hoy es probable que llueva", summary)
        self.assertIn("Agenda de hoy:\n• 09:00 Junta\n• Todo el día: Feriado", summary)

    def test_a_failure_outside_never_breaks_the_summary(self):
        def broken(*_):
            raise RuntimeError("caído")

        self.assistant.weather = broken
        self.assistant.agenda = broken
        self.assertIn("Buen día", self.assistant.build_summary())


class CalendarClientTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.client_path = self.root / "google-client.json"
        self.client_path.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "secreto"}}), encoding="utf-8")
        self.token_path = calendar_token_path(self.root, "personal")
        self.token_path.write_text(json.dumps({"refresh_token": "renovar"}), encoding="utf-8")
        self.items = []
        self.requests = []

    def fetch(self, request):
        self.requests.append(request)
        if "oauth2" in request.full_url:
            return json.dumps({"access_token": "llave", "expires_in": 3600}).encode("utf-8")
        return json.dumps({"items": self.items}).encode("utf-8")

    def test_reads_cleans_and_filters_events(self):
        self.items = [
            {"id": "a", "summary": "Junta con Ana https://malo.example/x", "start": {"dateTime": "2026-11-10T15:00:00Z"}},
            {"id": "b", "summary": "Feriado", "start": {"date": "2026-11-10"}},
            {"id": "c", "summary": "Cancelada", "status": "cancelled", "start": {"dateTime": "2026-11-10T10:00:00-06:00"}},
            {"id": "d", "summary": "Rechazada", "start": {"dateTime": "2026-11-10T11:00:00-06:00"},
             "attendees": [{"self": True, "responseStatus": "declined"}]},
            {"id": "e", "start": {"dateTime": "no es fecha"}},
            {"id": "f", "start": {"dateTime": "2026-11-10T12:00:00-06:00"}},
        ]
        start = NOW.replace(hour=0)
        events = CalendarClient(self.client_path, self.token_path, self.fetch).events(start, start + timedelta(days=1), "trabajo")
        self.assertEqual([e.id for e in events], ["a", "b", "f"])
        self.assertEqual(events[0].label(), "[trabajo] 09:00 Junta con Ana")  # Sin el enlace y en la hora local.
        self.assertEqual(events[1].label(), "[trabajo] Todo el día: Feriado")
        self.assertEqual(events[2].title, "(sin título)")
        query = self.requests[-1].full_url
        self.assertTrue(query.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events?"))
        self.assertIn("singleEvents=true", query)

    def test_accounts_are_found_by_their_own_key_files(self):
        calendar_token_path(self.root, "trabajo").write_text("{}", encoding="utf-8")
        (self.root / "google-token.json").write_text("{}", encoding="utf-8")  # La del correo no cuenta.
        self.assertEqual([name for name, _ in find_calendars(self.root)], ["trabajo", "personal"])


class FakeCalendar:
    def __init__(self, events=(), error=None):
        self.result, self.error, self.calls = list(events), error, 0

    def events(self, start, end, account):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class AgendaTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.sent = []
        self.calendar = FakeCalendar([
            Event("b", "Dentista", datetime(2026, 11, 10, 16, 0, tzinfo=TZ)),
            Event("x", "Feriado", None),
            Event("a", "Junta", datetime(2026, 11, 10, 9, 0, tzinfo=TZ)),
        ])
        self.agenda = Agenda([("personal", self.calendar)], self.store, 15, lambda text, buttons: self.sent.append(text))

    def test_day_view_is_sorted_and_cached(self):
        self.assertEqual(self.agenda.today_lines(NOW), ["Todo el día: Feriado", "09:00 Junta", "16:00 Dentista"])
        self.agenda.today_lines(NOW + timedelta(minutes=4))
        self.assertEqual(self.calendar.calls, 1)
        self.agenda.today_lines(NOW + timedelta(minutes=6))
        self.assertEqual(self.calendar.calls, 2)

    def test_reminds_once_shortly_before_each_event(self):
        self.agenda.tick(NOW.replace(hour=8, minute=44))
        self.assertEqual(self.sent, [])
        self.agenda.tick(NOW.replace(hour=8, minute=45))
        self.agenda.tick(NOW.replace(hour=8, minute=50))
        self.assertEqual(self.sent, ["📅 En 15 min: 09:00 Junta"])
        Agenda([("personal", self.calendar)], self.store, 15, lambda t, b: self.sent.append(t)).tick(NOW.replace(hour=8, minute=55))
        self.assertEqual(len(self.sent), 1)  # Tampoco se repite después de reiniciar.
        self.agenda.tick(NOW.replace(hour=9, minute=30))
        self.assertEqual(len(self.sent), 1)  # Uno que ya empezó no se avisa tarde.

    def test_lost_permission_pauses_instead_of_hammering(self):
        self.calendar.error = GmailAuthError("vencida")
        self.assertEqual(self.agenda.today_lines(NOW), [])
        self.agenda.today_lines(NOW + timedelta(minutes=10))
        self.assertEqual(self.calendar.calls, 1)

    def test_zero_minutes_turns_reminders_off(self):
        Agenda([("personal", self.calendar)], self.store, 0, lambda t, b: self.sent.append(t)).tick(NOW.replace(hour=8, minute=50))
        self.assertEqual(self.sent, [])


class HeartbeatTests(unittest.TestCase):
    def test_only_https_addresses(self):
        self.assertTrue(valid_heartbeat("https://vigilante.example/ping/abc"))
        for bad in ("http://vigilante.example/ping", "vigilante.example", "file:///c:/x", ""):
            self.assertFalse(valid_heartbeat(bad), bad)

    def test_keeps_pinging_through_failures(self):
        stop = threading.Event()
        visits = []

        def fetch(url):
            visits.append(url)
            if len(visits) == 1:
                raise OSError("sin red")
            if len(visits) == 3:
                stop.set()
            return b"ok"

        run_heartbeat("https://vigilante.example/ping", stop, interval=0, fetch=fetch)
        self.assertEqual(visits, ["https://vigilante.example/ping"] * 3)


if __name__ == "__main__":
    unittest.main()
