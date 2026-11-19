# Tareas — Spec 001: Rediseño visual de la página de Hermes

Parte de `plan.md` (aprobado el 2026-11-17, decisiones P1-P3). 23 tareas en 3 lotes. Todas
salvo T3 son secuenciales: casi todas tocan `hermes/status.py` (compartido).

Convenciones de esta lista:
- **Tests:** `~/.hermes/venv/Scripts/python.exe -m unittest discover -s tests` (se recomienda
  añadir `-W error::SyntaxWarning`), desde la raíz, sin `cd`.
- **Verificación de interfaz [P2, Cambio 2026-11-18]:** T1–T6 se verificaron parando Hermes
  (con aviso y sí del usuario) y levantando la demo en 47822. **Desde T7** la demo corre en
  http://127.0.0.1:47823 (`tests/browser/demo_server.py --puerto 47823`) con datos ficticios en
  base temporal y **el Hermes real no se para**; se verifica con el MCP de Playwright (375×812 y
  1280×800, claro y oscuro con `browser_emulate_media`, consola sin errores y sin peticiones
  fallidas) ejecutando `tests/browser/medir.js` con `browser_evaluate` (sus cuatro listas vacías
  en las vistas que diga la tarea) y después se para el servidor de demostración. Al cerrar cada
  lote (T10, T17, T23) se comprueba http://127.0.0.1:47822 (el Hermes real) sin capturas ni
  datos: solo que carga, consola, peticiones fallidas y scroll horizontal, informando solo
  cantidades. Desviación aceptada explícitamente por el usuario para esta spec (ver plan.md).
- **Checkpoint visual:** capturas en `specs/001-rediseno-visual/checkpoint/Tn-<ancho>-<claro|oscuro>.png`
  (no se versionan); sin el sí del usuario no empieza la siguiente tarea de interfaz.
- **Archivos nuevos:** los 9 del plan (N1-N9) están aprobados en la lista del plan; cada tarea que
  crea uno lo nombra y se confirma con el usuario antes de crearlo. Ninguno más sin preguntar.
- RNF-3 (tests en verde) y RNF-5 (español) aplican a todas las tareas.

## Lote A — Base, marco y Tareas

- [x] **T1. Lista de referencia de textos visibles, ids y clases (antes de tocar nada) y su test. Crea los archivos nuevos N5 `tests/test_page_texts.py` y N6 `tests/data/page_reference.json` (carpeta `tests/data/` nueva): confirmar con el usuario antes de crearlos.** RF-32, RF-33, RNF-8
 - Depende de: ninguna
 - Toca: tests/test_page_texts.py, tests/data/page_reference.json (compartido)
 - Paralelo: no
 - Hecho cuando: `page_reference.json` se ha generado con `extraer(PAGE)` sobre el `status.py` sin cambios (plan 3.4); `RENAMES` y `ACCESIBLES` existen vacíos; el test incluye casos conocidos de la extracción (un texto, un id y una clase del script) y el comando de tests está en verde.

- [x] **T2. Documento de diseño `docs/design.md` a partir del apartado 4 del plan. Crea el archivo nuevo N1 `docs/design.md`: confirmar antes de crearlo; el usuario aprueba el documento.** RF-1, RF-2, RF-3, RF-4, RF-8, RF-9, RF-31, RF-39, RF-41, RF-49
 - Depende de: ninguna
 - Toca: docs/design.md
 - Paralelo: no
 - Hecho cuando: `docs/design.md` recoge modo Operar, principios, tabla de tokens (color claro/oscuro, tipografía, espaciado, radios, movimiento, layout) con nombre, valor y escala en formato que pueda leer el test, tabla «Contraste» (color, fondo, mínimo, en claro y oscuro), regla de atenuación de categoría, colores de datos con el método de daltonismo, neutro del manifiesto, retirada del tema negro y dorado, componentes y estados del marco y de cada vista, acción principal por vista, logo e iconos, anti-patrones, referencias (Raycast y Linear: qué se adopta y qué se descarta) y la tabla «Excepciones» E1-E6 con la constancia de aprobación; el usuario lo ha aprobado; el comando de tests sigue en verde.

- [x] **T3. Test de tokens, contraste y daltonismo con todas las secciones de CSS marcadas `@legacy`. Crea el archivo nuevo N4 `tests/test_design_tokens.py`: confirmar antes de crearlo.** RF-2, RF-8, RF-11, RF-13, RF-27, RF-31, RF-39, RF-49, RNF-6
 - Depende de: T2
 - Toca: tests/test_design_tokens.py
 - Paralelo: sí
 - Hecho cuando: el test implementa los parsers y cálculos de los planes 3.2 y 3.3 con pruebas de casos conocidos (contraste negro/blanco = 21:1, un literal de color detectado, una excepción de la tabla aceptada); valida la tabla de `docs/design.md` (contraste de cada par ≥ su mínimo y ΔE76 ≥ 20 entre `--data-1` y `--data-2` con protanopía, deuteranopía y tritanopía, en los dos modos); la comprobación de `:root` y de las declaraciones se salta las secciones marcadas `/* @legacy <vista> */` y, mientras `:root` no esté migrado, también se marca como pendiente; el comando de tests está en verde.

- [x] **T4. Tipografía propia: descarga con permiso, ruta `/fonts/…`, `font-src 'self'` en la CSP y sus tests. Antes de descargar, pedir permiso al usuario con nombre (Atkinson Hyperlegible Next, woff2 variable, subconjunto latín), origen, URL exacta del archivo, licencia (SIL OFL 1.1) y tamaño exacto. Antes de tocar `status.py`, confirmar la excepción de seguridad de RF-48 (ruta nueva y cambio de CSP). Crea los archivos nuevos N2 `hermes/assets/fonts/atkinson-hyperlegible-next-latin.woff2` y N3 `hermes/assets/fonts/OFL.txt` (carpeta `fonts/` nueva).** RF-48, RNF-1, RNF-2
 - Depende de: T1
 - Toca: hermes/assets/fonts/atkinson-hyperlegible-next-latin.woff2, hermes/assets/fonts/OFL.txt, hermes/status.py (compartido), tests/test_status.py, tests/test_remote.py
 - Paralelo: no
 - Hecho cuando: el usuario ha dado el permiso de descarga y el sí a la excepción de RF-48; la fuente tiene los glifos del español y cifras tabulares (si no, se para y se propone Public Sans); `FONT_FILES` es un diccionario cerrado fuera de `PUBLIC_FILES` (plan 3.1); `tests/test_status.py` comprueba 200 `font/woff2` con firma `wOF2`, 404 para `/fonts/OFL.txt`, `/fonts/../logo.webp`, `/fonts/icon-192.png` y `/fonts/`, 403 con Host ajeno, y CSP = la anterior + `font-src 'self'`; `tests/test_remote.py` comprueba 401 sin sesión, `PUBLIC_FILES` igual que antes y la pantalla de acceso sin `@font-face`; `remote.py` sin cambios (P1); el comando de tests está en verde.

- [x] **T5. Servidor de demostración con datos ficticios y script de medición en el navegador. Crea los archivos nuevos N7 `tests/browser/demo_server.py` y N8 `tests/browser/medir.js` (carpeta `tests/browser/` nueva): confirmar antes de crearlos. La prueba del servidor en 47822 para y reinicia Hermes (P2): avisar y esperar el sí.** RF-24, RF-25, RF-27, RNF-4, RNF-7
 - Depende de: ninguna
 - Toca: tests/browser/demo_server.py, tests/browser/medir.js
 - Paralelo: no
 - Hecho cuando: `demo_server.py` sirve la página en 127.0.0.1:47822 con SQLite temporal y datos ficticios que llenan todas las vistas y subpestañas (incluidos títulos largos, muchas categorías, contadores de 3 dígitos, gráfico con dos series), sin red ni `.env` real, y admite arrancar sin el archivo de fuente; `medir.js` devuelve el JSON de cuatro listas del plan 3.6; probado una vez con la verificación [P2] sobre la página actual (sus resultados se guardan solo como referencia, no tienen que salir vacíos); `unittest discover` no lo recoge y el comando de tests está en verde.

- [x] **T6. Tokens en `:root` con modo claro y oscuro, `color-scheme`, `@font-face` local, dos metas `theme-color`, `status-bar-style` y colores del manifiesto, y retirada de `body.stage`.** RF-5, RF-6, RF-7, RF-8, RF-9, RF-10, RF-11, RF-33, RF-36, RF-41, RF-48, RNF-1
 - Depende de: T1, T2, T3, T4, T5
 - Toca: hermes/status.py (compartido), tests/test_status.py, tests/test_page_texts.py
 - Paralelo: no
 - Hecho cuando: `:root` y su `@media (prefers-color-scheme: dark)` coinciden con la tabla de `docs/design.md` (los alias viejos que aún usen secciones `@legacy` quedan marcados `@legacy` y se retiran en T23); `tests/test_status.py` comprueba el manifiesto con `#56646A` y sin `#0a0c0f`, las dos metas `theme-color` con `media`, `status-bar-style` `default` y `PAGE` sin `class="stage"`; `RENAMES` incluye `stage`; el comando de tests está en verde; verificación [P2]: al cambiar de modo con texto escrito la paleta cambia sin recargar y lo escrito se conserva, la fuente carga sin errores de CSP.

- [x] **T7. Marco: cabecera, pestañas, indicador de conexión, subpestañas, botones (principal, secundario, peligro, icono), campos, foco, aviso emergente y franja «Hermes no responde». Pantalla nueva: checkpoint visual. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-13, RF-14, RF-15, RF-16, RF-18, RF-23, RF-24, RF-25, RF-26, RF-28, RF-37
 - Depende de: T6
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: las secciones de CSS del marco ya no llevan `@legacy` y pasan el test de tokens; pestaña y subpestaña activas se distinguen por subrayado/borde y peso; el indicador usa `--ok`/`--danger` con forma distinta; el aviso no tapa el botón de hablar ni la acción principal; el comando de tests está en verde; verificación [P2] de la vista Tareas con `medir.js` vacío en el marco, foco visible con Tab; capturas del checkpoint aprobadas por el usuario.

- [x] **T8. Diálogos (editor de tarea, confirmación, foto de recibo): tokens, hoja inferior con acciones fijas al pie, foco dentro, Escape y foco devuelto. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-7, RF-17, RF-29
 - Depende de: T7
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: sus secciones de CSS sin `@legacy` y el test de tokens en verde; `openDialog` guarda el control de origen y el evento `close` le devuelve el foco (plan 3.5), también al cerrar con ✕; `test_page_texts` sin textos visibles nuevos; el comando de tests está en verde; verificación [P2]: a 375×812 Guardar, confirmar y Cerrar se ven sin desplazar, Escape cierra, el foco vuelve al control que abrió, cambiar de modo con el editor abierto no lo cierra ni pierde lo escrito.

- [x] **T9. Botón de hablar y panel de voz: tokens, estados por icono además del color, zonas seguras y reducir movimiento (excepción E4). Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-26, RF-30, RF-31, RF-38
 - Depende de: T8
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: sus secciones sin `@legacy` y el test de tokens en verde (el pulso y el giro aceptados solo como E4); el comando de tests está en verde; verificación [P2]: reposo, grabando (■ y `--danger`), pensando (icono de espera) y hablando se distinguen por icono; con `prefers-reduced-motion: reduce` no hay pulso, giro ni desplazamientos; `medir.js` vacío para el botón y el panel.

- [x] **T10. Vista Tareas: entrada, contadores tabulares, Lista/Calendario, Calendario, filtros, grupos, tarjetas con glifo de urgencia, hecha/pendiente, y estados de carga (esqueleto + `.sr-only` + `aria-busy`), vacío y error. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-10, RF-12, RF-19, RF-20, RF-21, RF-22, RF-23, RF-24, RF-35, RF-40
 - Depende de: T9
 - Toca: hermes/status.py (compartido), tests/test_page_texts.py
 - Paralelo: no
 - Hecho cuando: las secciones de Tareas sin `@legacy` y el test de tokens en verde; el anuncio de carga figura en `ACCESIBLES` y `test_page_texts` no encuentra otros textos nuevos; el comando de tests está en verde; verificación [P2] de Tareas (Lista y Calendario) con `medir.js` vacío en los cuatro casos, urgente/vencida/hecha distinguibles por glifo o peso además del color, título largo cortado a 2 líneas y completo en el editor, lista vacía con su texto de hoy, y sin desborde con 200 % de texto; cierre del lote A: comprobación en http://127.0.0.1:47822 (Hermes real) sin capturas y sin leer ni describir datos (carga, consola sin errores, sin peticiones fallidas y sin scroll horizontal), informando solo cantidades.

## Lote B — Apuntes

- [x] **T11. Marco de Apuntes (título, explicación, subpestañas, aviso de silencio, estado de carga con esqueleto + `.sr-only` + `aria-busy`) y subpestaña Listas. Pantalla nueva: checkpoint visual. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-15, RF-34, RF-42, RF-47
 - Depende de: T10
 - Toca: hermes/status.py (compartido), tests/test_page_texts.py
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: las secciones de Apuntes comunes y Listas sin `@legacy` y el test de tokens en verde; el anuncio de carga de Apuntes en `ACCESIBLES`; el comando de tests está en verde; verificación [P2] de Apuntes → Listas con `medir.js` vacío, las 8 subpestañas alcanzables desplazando su fila sin desplazar la página, estado vacío con su texto de hoy; capturas del checkpoint aprobadas por el usuario.

- [x] **T12. Apuntes → Hábitos: botón de hoy, semana de 7 días con zonas de 44 px y racha. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-25, RF-34, RF-42, RF-47
 - Depende de: T11
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: la sección de Hábitos sin `@legacy` y el test de tokens en verde; el comando de tests está en verde; verificación [P2] de Hábitos con `medir.js` vacío (los 7 días caben a 375 px con zona ≥ 44 px) y su estado vacío.

- [x] **T13. Apuntes → Notas y Seguimientos. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-24, RF-34, RF-42, RF-47
 - Depende de: T12
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: sus secciones sin `@legacy` y el test de tokens en verde; el comando de tests está en verde; verificación [P2] de Notas y Seguimientos con `medir.js` vacío, nombres largos sin desbordar y estados vacíos con su texto de hoy.

- [x] **T14. Apuntes → Fechas: calendario con números de día tabulares, hoy en neutro invertido, distintivos y próximas. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-12, RF-24, RF-34, RF-42, RF-47
 - Depende de: T13
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: la sección de Fechas sin `@legacy` y el test de tokens en verde; el comando de tests está en verde; verificación [P2] de Fechas con `medir.js` vacío y el calendario sin desplazamiento horizontal de la página a 375 px.

- [x] **T15. Apuntes → Gastos: navegación de mes, total e importes tabulares, barras de presupuesto (aviso y peligro) y miniatura de la foto de recibo. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-12, RF-25, RF-34, RF-42, RF-47
 - Depende de: T14
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: la sección de Gastos sin `@legacy` y el test de tokens en verde; el comando de tests está en verde; verificación [P2] de Gastos con `medir.js` vacío, importes con cifras tabulares, miniatura con zona ≥ 44 px que abre el diálogo de foto.

- [x] **T16. Apuntes → Pagos: formulario, próximos en aviso, vencidos en peligro e importes tabulares. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-12, RF-34, RF-42, RF-47
 - Depende de: T15
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: la sección de Pagos sin `@legacy` y el test de tokens en verde; el comando de tests está en verde; verificación [P2] de Pagos con `medir.js` vacío, vencidos distinguibles por borde y texto además del color, y estado vacío con su texto de hoy.

- [x] **T17. Apuntes → Lecturas: formulario y lista con enlaces largos cortados. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-24, RF-34, RF-40, RF-42, RF-47
 - Depende de: T16
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Hecho cuando: la sección de Lecturas sin `@legacy` y ninguna sección de Apuntes queda `@legacy`; el test de tokens y el comando de tests están en verde; verificación [P2] de todas las subpestañas de Apuntes con `medir.js` vacío, enlace largo sin desbordar y sin desborde con 200 % de texto; cierre del lote B: comprobación en http://127.0.0.1:47822 (Hermes real) sin capturas y sin leer ni describir datos (carga, consola sin errores, sin peticiones fallidas y sin scroll horizontal), informando solo cantidades.

## Lote C — Demás vistas, logo y cierre

- [x] **T18. Vista Consumo: cifras tabulares, gráfico de 14 columnas con `--data-1` lisa y `--data-2` rayada, leyenda en texto, tooltip, vista como tabla, tablas con desplazamiento interno, estado de carga con esqueleto + `.sr-only` + `aria-busy`, y renombre `--s-claude`/`--s-local` → `--data-1`/`--data-2`. Pantalla nueva: checkpoint visual. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-12, RF-25, RF-33, RF-34, RF-43, RF-47, RF-49, RF-50
 - Depende de: T17
 - Toca: hermes/status.py (compartido), tests/test_page_texts.py
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: las secciones de Consumo sin `@legacy` y el test de tokens en verde (`.col` aceptada solo como E1); `RENAMES` incluye `--s-claude` y `--s-local`, el nombre viejo no aparece en ningún uso y el anuncio de carga figura en `ACCESIBLES`; el comando de tests está en verde; verificación [P2] de Consumo con `medir.js` vacío (barras ≥ 3:1 contra el fondo del gráfico en los dos modos), 14 días sin desplazamiento a 375 px, cada columna activable en toda su franja con alto ≥ 44 px, leyenda con los dos nombres también con una sola serie o sin datos; capturas del checkpoint aprobadas por el usuario.

- [x] **T19. Vista Historial: buscador, burbujas, separador de día y lista de escuchas por voz, con sus estados vacío y error. Pantalla nueva: checkpoint visual. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-24, RF-34, RF-44, RF-47
 - Depende de: T18
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: las secciones de Historial sin `@legacy` y el test de tokens en verde; el comando de tests está en verde; verificación [P2] de Historial con `medir.js` vacío, enlaces largos sin desbordar y estado vacío con su texto de hoy; capturas del checkpoint aprobadas por el usuario.

- [x] **T20. Vista En vivo: sin tema negro y dorado ni degradado, anillos y ondas con el acento (excepción E3), disco con la superficie del modo, logo atenuado en pausa, mensaje y pista, botón del micrófono, medidor sin transición, estado de carga con esqueleto + `.sr-only` + `aria-busy`, y reducir movimiento. Pantalla nueva: checkpoint visual. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-9, RF-30, RF-31, RF-34, RF-45, RF-47
 - Depende de: T19
 - Toca: hermes/status.py (compartido), tests/test_page_texts.py
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: las secciones de En vivo sin `@legacy` y el test de tokens en verde (ondas y «respirar» aceptados solo como E3); el anuncio de carga en `ACCESIBLES`; el comando de tests está en verde; verificación [P2] de En vivo con `medir.js` vacío, estados distinguibles por su texto e indicador además del color, con `prefers-reduced-motion: reduce` sin ondas ni escalas; capturas del checkpoint aprobadas por el usuario (incluido el estado en pausa).

- [x] **T21. Vista Ajustes: aviso de reinicio, dispositivos, grupos con todos sus controles (Funciones, interruptores con `accent-color`, chips de categoría con el selector de color tal cual, excepción E2) y barra de Guardar. Pantalla nueva: checkpoint visual. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-8, RF-25, RF-34, RF-46, RF-47
 - Depende de: T20
 - Toca: hermes/status.py (compartido)
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: las secciones de Ajustes sin `@legacy` y el test de tokens en verde (`.chip-color` aceptado solo como E2); los colores de categoría se siguen guardando igual; el comando de tests está en verde; verificación [P2] de Ajustes con `medir.js` vacío, una columna a ≤ 640 px, ✕ de los chips con zona ≥ 44 px y selector de color sin vista previa añadida; capturas del checkpoint aprobadas por el usuario.

- [x] **T22. Logo, iconos de la app instalada y marca de la cabecera: `docs/logo.svg`, rasterizado con el navegador del MCP a `logo.webp`, `icon-192.png` e `icon-512.png` (mismos nombres, rutas y tamaños), y `.brand-dot` → `.brand-mark` en SVG en línea. Crea el archivo nuevo N9 `docs/logo.svg`: confirmar antes de crearlo. Checkpoint visual de logo e iconos. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-14, RF-33, RF-51, RF-52
 - Depende de: T21
 - Toca: docs/logo.svg, hermes/assets/logo.webp, hermes/assets/icon-192.png, hermes/assets/icon-512.png, hermes/status.py (compartido), tests/test_page_texts.py
 - Paralelo: no
 - Checkpoint: visual
 - Hecho cuando: los tres archivos tienen los mismos nombres y tamaños que antes (1254×1254, 192×192, 512×512) y se sirven por las mismas rutas, sin rutas nuevas; `RENAMES` incluye `.brand-dot` → `.brand-mark` y el nombre viejo no aparece en ningún uso; el comando de tests está en verde; los intermedios se generan en el directorio temporal de la sesión, no en el repositorio; capturas del checkpoint (192, 512 y logo; icono a 16 y 32 px sobre claro y oscuro; máscara de esquinas de iOS al 22 %; logo dentro de En vivo en claro, oscuro y pausa) aprobadas por el usuario.

- [x] **T23. Cierre: sin secciones `@legacy` ni alias viejos, medición completa, texto al 200 %, sin la fuente, teclado y reducir movimiento en todas las vistas, `docs/design.md` al día (contrastes medidos y excepciones aprobadas) y comprobación manual del usuario en el iPhone. Verificación con la demo en 47823, sin parar Hermes (P2, cambio del 2026-11-18).** RF-4, RF-11, RF-13, RF-24, RF-25, RF-26, RF-27, RF-28, RF-30, RF-31, RF-32, RF-34, RF-36, RF-39, RF-40, RF-41, RF-52, RNF-3, RNF-4, RNF-6, RNF-7, RNF-8
 - Depende de: T22
 - Toca: hermes/status.py (compartido), tests/test_design_tokens.py, tests/test_page_texts.py, docs/design.md
 - Paralelo: no
 - Hecho cuando: el test de tokens exige `LEGACY == ∅` y ya no admite pendiente en `:root`; los alias viejos (`--card`, `--muted`, `--faint`, `--soft`, `--bar`, `--shadow`) están retirados, figuran en `RENAMES` y no aparecen en ningún uso; `docs/design.md` tiene los contrastes medidos y todas las excepciones usadas, cada una aprobada (si apareció alguna nueva, aprobada una a una); el comando de tests está en verde; verificación [P2] de todas las vistas y subpestañas con `medir.js` vacío a 375×812 y 1280×800 en claro y oscuro, consola y peticiones sin fallos, texto al 200 % sin solapes, servidor de demostración sin el archivo de fuente sin desborde ni errores de CSP, recorrido con teclado (Tab en orden visual, Escape en diálogos) y con reducir movimiento; el usuario confirma en su iPhone las zonas seguras, la barra de estado y el color de tema según el modo, y el icono nuevo tras reinstalar la app; cierre del lote C y de la spec: comprobación en http://127.0.0.1:47822 (Hermes real) sin capturas y sin leer ni describir datos (carga, consola sin errores, sin peticiones fallidas y sin scroll horizontal), informando solo cantidades.
 - Comprobación manual en el iPhone (RF-26, RF-41, RF-52): hecha por el usuario el 2026-11-18, con Hermes ya reiniciado y sirviendo las correcciones de la validación; confirmó que todo estaba bien.

## Cobertura RF → tareas

| RF | Tareas | RF | Tareas |
|---|---|---|---|
| RF-1 | T2 | RF-27 | T3, T5, T23 |
| RF-2 | T2, T3 | RF-28 | T7, T23 |
| RF-3 | T2 | RF-29 | T8 |
| RF-4 | T2, T23 | RF-30 | T9, T20, T23 |
| RF-5 | T6 | RF-31 | T2, T3, T9, T20, T23 |
| RF-6 | T6 | RF-32 | T1, T23 |
| RF-7 | T6, T8 | RF-33 | T1, T6, T18, T22 |
| RF-8 | T2, T3, T6, T21 | RF-34 | T11-T21, T23 |
| RF-9 | T2, T6, T20 | RF-35 | T10 |
| RF-10 | T6, T10 | RF-36 | T6, T23 |
| RF-11 | T3, T6, T23 | RF-37 | T7 |
| RF-12 | T10, T14, T15, T16, T18 | RF-38 | T9 |
| RF-13 | T3, T7, T23 | RF-39 | T2, T3, T23 |
| RF-14 | T7, T22 | RF-40 | T10, T17, T23 |
| RF-15 | T7, T11 | RF-41 | T2, T6, T23 |
| RF-16 | T7 | RF-42 | T11-T17 |
| RF-17 | T8 | RF-43 | T18 |
| RF-18 | T7 | RF-44 | T19 |
| RF-19 | T10 | RF-45 | T20 |
| RF-20 | T10 | RF-46 | T21 |
| RF-21 | T10 | RF-47 | T11-T21 |
| RF-22 | T10 | RF-48 | T4, T6 |
| RF-23 | T7, T10 | RF-49 | T2, T3, T18 |
| RF-24 | T5, T7, T10, T13, T14, T17, T19, T23 | RF-50 | T18 |
| RF-25 | T5, T7, T12, T15, T18, T21, T23 | RF-51 | T22 |
| RF-26 | T7, T9, T23 | RF-52 | T22, T23 |

RNF: RNF-1 T4, T6 · RNF-2 T4 · RNF-3 todas · RNF-4 T5, T23 · RNF-5 todas · RNF-6 T3, T23 ·
RNF-7 T5, T23 · RNF-8 T1, T23.
