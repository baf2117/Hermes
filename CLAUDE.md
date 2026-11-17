# CLAUDE.md

Este archivo guía a Claude Code (claude.ai/code) en este repositorio.
Plantilla SDD: versión **0.7.0** (ver `VERSION` y `CHANGELOG.md`). Quedan [CORCHETES] por
rellenar; bórralos al completarlos.

## Qué es esto

Hermes — asistente personal local en español que corre en una laptop con Windows: tareas,
recordatorios, correo, calendario, gastos, pagos, hábitos y voz, por Telegram y por una
página local. Versión 2.0.0 (`hermes/__init__.py`), en uso diario.

## Estructura del repo

- `hermes/` — el paquete: `__main__.py` (arranque y conexión de las piezas), `assistant.py`
  (interpreta los mensajes), `store.py` (SQLite), `status.py` (página local), `telegram.py`,
  `llm.py` (modelo local con Ollama), `settings.py` y `config.py` (ajustes), y un módulo por
  función (`receipts.py`, `bills.py`, `links.py`, `search.py`…)
- `hermes/assets/` — logo e íconos de la página
- `tests/` — pruebas con `unittest`
- `evals/` — `eval_intents.py`: mide cómo interpreta el modelo real frases en español
- `.env.example` — ejemplo de configuración; el `.env` real no se versiona
- `docs/` — `constitution.md` (principios innegociables) y, si existen, `ARCHITECTURE.md`
  (el "por qué" de las decisiones) y `design.md` (decisiones de diseño visual)
- `specs/` — una carpeta por spec (`specs/NNN-nombre/`)
- `.claude/` — skill `sdd`, comandos y agentes del flujo SDD
- `VERSION` — versión de la plantilla SDD usada (cambios en `CHANGELOG.md`)

## Comandos

Los agentes leen estos comandos de aquí: mantenlos al día.

- **Instalar dependencias:** `[comando]` (no hay `requirements.txt` ni `pyproject.toml`;
  el entorno está en `~/.hermes/venv`, con Python 3.13)
- **Levantar en local:** `~/.hermes/venv/Scripts/python.exe -m hermes` (http://127.0.0.1:47822).
  En el día a día lo arranca la tarea programada «Hermes». `python -m hermes check` revisa la
  configuración.
- **Comando de tests:** `~/.hermes/venv/Scripts/python.exe -m unittest discover -s tests`
  (sin `cd`, desde la raíz del proyecto, para coincidir con los permisos del `reviewer`)
- **Compilar / lint:** [comando] (no hay linter configurado)

### Flujo SDD

```bash
claude --agent sdd-coordinator    # spec → clarificación → plan → tareas → implementación → validación → commit → integración
```

Pasos sueltos: `/sdd-constitution`, `/sdd-spec`, `/sdd-clarify`, `/sdd-plan`, `/sdd-tasks`,
`/sdd-implement`, `/sdd-validate`, `/sdd-change`, `/sdd-status`. Para cambios pequeños sin
spec: `/features`. Si el proyecto es un fork: `/sync-upstream`.

## Arquitectura

[Decisiones que no se deducen leyendo el código: cómo fluyen los datos, dónde vive la
lógica, qué no hay que tocar. Si crece, muévelo a `docs/ARCHITECTURE.md`.]

## Referencia del stack

| Capa | Servicio / tecnología |
|---|---|
| Lenguaje | Python 3.13, sin framework web (`http.server` de la biblioteca estándar) |
| Interfaz | Página local en `hermes/status.py` (HTML, CSS y JS en línea) y bot de Telegram |
| Datos | SQLite (`hermes/store.py`) y `.env` en la carpeta de datos (`~/.hermes`) |
| Modelos | Ollama local (`hermes/llm.py`) y Claude Code CLI (`hermes/claude_cli.py`) |
| Voz | faster-whisper, vosk, piper, kokoro-onnx, edge-tts, sounddevice |
| Externos | Gmail y Google Calendar (`hermes/gmail.py`, `hermes/outside.py`) |

## Convenciones

- Interfaz, mensajes y comentarios en español.
- [Estilo de código, nombres.]
- [Ejecución paralela: máximo de implementers a la vez (por defecto 2) y qué recursos
  comparten los tests (base de datos, puertos, servidor), para marcar `Paralelo: no`.]
- [Si hay interfaz: responsive, modo oscuro, accesibilidad. El diseño sigue la skill
  `sdd-design` y queda registrado en `docs/design.md`; las referencias analizadas con
  `/taste` van en `docs/references/`.]

## Personalizaciones de la plantilla

Archivos de la plantilla SDD que este proyecto modificó a propósito (se conservan al
actualizar la plantilla; ver `CHANGELOG.md`).

- [Ninguna. Ejemplo: `.claude/agents/reviewer.md` — añadido `Bash(make test:*)`.]

## Memoria

- Al empezar, lee `MEMORY.md` para conocer el estado del proyecto y las decisiones
  tomadas.
- Al terminar una spec, o cuando haya una decisión importante o un error que valga la
  pena recordar, actualízalo: estado actual, decisiones (con su porqué) y errores a evitar.
- Mantenlo breve (máximo ~50 líneas): resume o elimina lo que ya no aporte.
- Si algo se convierte en una regla permanente, propón moverlo a `CLAUDE.md` o a
  `docs/constitution.md` en lugar de dejarlo en la memoria.
- No guardes nunca datos sensibles (claves, tokens, datos personales).

## Forma de trabajar

- Haz solo lo que se pide: no añadas funcionalidades por tu cuenta.
- Cambios pequeños y enfocados; no reescribas lo que ya funciona.
- Al terminar, resume qué has cambiado y cualquier decisión que deba revisar.
- En una pantalla nueva, antes de construirla, presenta el plan de diseño y espera mi
  aprobación.

## Límites

- ✅ Siempre: [reglas que nunca se rompen, p. ej. idioma de la interfaz y los comentarios].
- ⚠️ Pregunta antes: crear archivos nuevos, cambiar el formato de los datos guardados,
  añadir dependencias.
- 📦 Al definir el stack o añadir una tecnología nueva, actualiza `.gitignore` con sus
  artefactos (compilados, cachés, ajustes locales). Parte de las plantillas de
  github/gitignore y contrasta con context7.
- 🚫 Nunca: escribir secretos en el repositorio (van en el `.env`, que no se versiona).
  [Otras.]

## Verificación

- Después de cada cambio, ejecuta el comando de tests.
- Si hay interfaz: verifica con el MCP de Playwright en http://127.0.0.1:47822: abre la URL,
  prueba la funcionalidad, revisa la consola y las peticiones fallidas, comprueba la vista
  móvil (`browser_resize` a 375×812) y el modo oscuro (`browser_emulate_media`).
- [Si hay login: usa un usuario de prueba, nunca credenciales reales; inicia sesión tú en
  la ventana de Playwright; el perfil se conserva entre sesiones.]

## Reglas

- Lee `docs/constitution.md` antes de tocar código y, si hay una spec activa
  (`specs/NNN-*/`), léela también.
