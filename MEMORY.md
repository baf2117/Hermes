# Memory

Memoria del proyecto entre sesiones. Máximo ~50 líneas: reescribe por secciones,
resume o elimina lo que ya no aporte. El detalle vive en `docs/`; aquí solo el
estado y los punteros. Nunca guardes claves, tokens ni datos personales.

## Estado actual
- Spec 001 «Rediseño visual» implementada en la rama `spec/001-rediseno-visual` (lotes A, B, C
  y cierre), validación APROBADA. 576 tests en verde.
- Lenguaje visual en `docs/design.md`: acento verdín, claro/oscuro según el sistema, fuente
  Atkinson Hyperlegible Next servida en local, logo con el monograma «H».

## Decisiones (con su porqué)
- Un solo acento por pantalla: el usuario lo pidió en el checkpoint de T11 (exceso de acento).
- Fuera el tema negro y dorado: el usuario quería un lenguaje único.
- Claro y oscuro solo según el sistema, sin interruptor.
- Fuente propia en `hermes/assets/fonts` con `FONT_FILES` (lista cerrada); la CSP solo añade
  `font-src 'self'`. Así se cumple «sin recursos externos».
- Logo: de la sandalia alada a la «H», coherente con `design.md` y aprobado por el usuario.
- Excepciones E1–E7 registradas en `docs/design.md`.
- Verificación P2: demo con datos ficticios en los puertos 47823/47825
  (`tests/browser/demo_server.py` y `medir.js`) sin parar el Hermes real; en 47822 se comprueba
  sin capturas al cerrar cada lote. Desviación aceptada por el usuario respecto a CLAUDE.md y
  al principio 4 de la constitución.

## Deudas aceptadas
- Pantallas de acceso y espera de `remote.py` siguen en negro y dorado: son de seguridad,
  necesitan su propia spec.
- La fuente se sirve con `Cache-Control: no-store` y se descarga en cada carga.
- El test de textos no detecta palabras sueltas nuevas en minúsculas.
- La ayuda del ajuste del tiempo en `hermes/settings.py` usa coordenadas de ejemplo que
  podrían ser reales: cambiarlas por 0.0,0.0.
- El hover de los pasos del editor no da una señal visible.
- Control inteligente de aplicaciones de Windows desactivado para que funcione el python del
  venv; puede que no se pueda volver a activar.

## Pendiente de decidir
- Si se añade ruff (con su propia spec).
- Si P2 (verificar con la demo en otro puerto) pasa a regla en CLAUDE.md o en la constitución.

## Aprendizajes y errores a evitar
- Reiniciar Hermes: `schtasks /End /TN "Hermes"`, esperar a que el puerto 47822 quede libre
  y luego `schtasks /Run`. Matar el PID deja la tarea atascada «En ejecución» sin escuchar.
- Parar los procesos y borrar las carpetas de la demo al terminar.
- Smart App Control (Device Guard) bloqueó el python del venv.
- `ConnectionAbortedError` intermitente en los tests de red: si aparece, repetirlos.

## Próximos pasos
1. El usuario hace push e integra la rama, o abre un PR.
2. Spec para el rediseño de las pantallas de `remote.py`.
3. Spec de ruff.
4. Deudas menores: `no-store` de la fuente y coordenadas de ejemplo.
