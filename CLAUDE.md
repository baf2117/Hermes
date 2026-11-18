# CLAUDE.md

Este archivo guía a Claude Code (claude.ai/code) en este repositorio.
Plantilla SDD: versión **0.7.0** (ver `VERSION` y `CHANGELOG.md`).

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

- **Instalar dependencias:** `uv pip install -r requirements.txt --python ~/.hermes/venv/Scripts/python.exe`
  (el entorno está en `~/.hermes/venv`, con Python 3.13, creado con uv y sin pip)
- **Levantar en local:** `~/.hermes/venv/Scripts/python.exe -m hermes` (http://127.0.0.1:47822).
  En el día a día lo arranca la tarea programada «Hermes». `python -m hermes check` revisa la
  configuración.
- **Comando de tests:** `~/.hermes/venv/Scripts/python.exe -m unittest discover -s tests`
  (sin `cd`, desde la raíz del proyecto, para coincidir con los permisos del `reviewer`)
- **Compilar / lint:** no hay linter todavía (pendiente: añadir ruff, con su propia spec).
  Mientras tanto, añadir `-W error::SyntaxWarning` al comando de tests hace que fallen los
  avisos de sintaxis (por ejemplo, secuencias `\` inválidas en textos).

### Flujo SDD

```bash
claude --agent sdd-coordinator    # spec → clarificación → plan → tareas → implementación → validación → commit → integración
```

Pasos sueltos: `/sdd-constitution`, `/sdd-spec`, `/sdd-clarify`, `/sdd-plan`, `/sdd-tasks`,
`/sdd-implement`, `/sdd-validate`, `/sdd-change`, `/sdd-status`. Para cambios pequeños sin
spec: `/features`. Si el proyecto es un fork: `/sync-upstream`.

## Arquitectura

- **Arranque:** `hermes/__main__.py` crea cada pieza y la conecta; es el único sitio que
  sabe de todas. Una función nueva se engancha ahí, no dentro de `assistant.py`.
- **Mensajes:** Telegram, la voz y la página entregan el texto a `Assistant`
  (`assistant.py`). Cada función se engancha con `text_hooks` (frases), `command_hooks`
  (`/comandos`), `button_hooks` (botones `accion:id`) y `summary_hooks` (resumen de la
  mañana). Lo que nadie reconoce lo interpreta el modelo.
- **Programado:** `scheduler.py` revisa cada minuto recordatorios y resúmenes; otras
  funciones se suman con `extra_ticks`.
- **Página:** `status.py` sirve la página y sus datos con `set_source` (GET) y `set_action`
  (POST); cada ruta nueva se añade también a las rutas permitidas. Los POST exigen el
  Origin de la página y el token `X-Hermes-Token`.
- **Datos:** todo se guarda con `store.py` (SQLite); los módulos no abren la base por su
  cuenta. Los ajustes viven en el `.env` de `~/.hermes` y se editan con `settings.py`; los
  marcados `live` se aplican sin reiniciar.
- **No tocar sin spec:** la seguridad de `status.py` y `remote.py` (Host, Origin, token,
  sesiones, aprobación por Telegram) y los permisos de solo lectura de `gmail.py`.

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
- Estilo: `from __future__ import annotations` y tipos en las firmas; identificadores en
  inglés; docstrings, comentarios y textos en español. Un módulo por función, con su test
  en `tests/test_<función>.py`. Sin límite fijo de largo de línea.
- Ejecución paralela: máximo 2 implementers a la vez. Los tests usan SQLite en memoria y
  puertos libres, así que no comparten recursos. `hermes/status.py` y `hermes/__main__.py`
  los tocan casi todas las funciones: márcalos `(compartido)` y esas tareas con `Paralelo: no`.
- Interfaz: todo se ve bien a 375 px (se usa como app en el teléfono), respeta el modo
  oscuro, los botones llevan `aria-label` y los controles se usan con teclado. Sin JS ni CSS
  externos: todo va en línea en `status.py` (lo exige la CSP de la página). El diseño sigue
  la skill `sdd-design` y queda registrado en `docs/design.md`; las referencias analizadas
  con `/taste` van en `docs/references/`.

## Personalizaciones de la plantilla

Archivos de la plantilla SDD que este proyecto modificó a propósito (se conservan al
actualizar la plantilla; ver `CHANGELOG.md`).

- `.claude/agents/reviewer.md` — añadido `Bash(~/.hermes/venv/Scripts/python.exe -m unittest:*)`
  a `tools`, para que pueda ejecutar el comando de tests (Hermes usa `unittest`, no pytest).

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

- ✅ Siempre:
  - Cada función nueva lleva su interruptor en Ajustes → Funciones.
  - Antes de cada commit, se revisa que no vaya ningún secreto.
  - Tras los tests, se prueba en la copia real de Hermes con datos temporales que luego se
    borran, y se reinicia.
  - Con correo, calendario u otros datos reales, se informan solo cantidades, nunca el contenido.
- ⚠️ Pregunta antes: crear archivos nuevos, cambiar el formato de los datos guardados,
  añadir dependencias.
- 📦 Al definir el stack o añadir una tecnología nueva, actualiza `.gitignore` con sus
  artefactos (compilados, cachés, ajustes locales). Parte de las plantillas de
  github/gitignore y contrasta con context7.
- 🚫 Nunca:
  - Escribir secretos en el repositorio (van en el `.env`, que no se versiona).
  - Hacer push: lo hace el usuario.
  - Cambiar ajustes del sistema o de seguridad: se le da el comando al usuario.
  - Descargar o instalar nada sin pedir permiso antes, con nombre, origen y tamaño.
  - Hacer público el repositorio.

## Verificación

- Después de cada cambio, ejecuta el comando de tests.
- Si hay interfaz: verifica con el MCP de Playwright en http://127.0.0.1:47822: abre la URL,
  prueba la funcionalidad, revisa la consola y las peticiones fallidas, comprueba la vista
  móvil (`browser_resize` a 375×812) y el modo oscuro (`browser_emulate_media`).
- Login: se verifica solo en local (http://127.0.0.1:47822), que no pide contraseña. El acceso
  remoto (Cloudflare Access, contraseña y aprobación por Telegram) nunca se prueba con
  credenciales reales.

## Reglas

- Lee `docs/constitution.md` antes de tocar código y, si hay una spec activa
  (`specs/NNN-*/`), léela también.
