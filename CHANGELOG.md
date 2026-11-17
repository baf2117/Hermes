# Changelog

Cambios de la plantilla SDD. El número de versión está en `VERSION`; cada proyecto debe
anotar en su `CLAUDE.md` qué versión usó para saber qué mejoras le faltan.

Cada versión tiene una sección **Migración** con los pasos exactos para un proyecto que
ya usa la plantilla. Aplícalas en orden, de la versión siguiente a la tuya hasta la
última. Archivos de la plantilla frente a archivos del proyecto: ver "Actualizar un
proyecto a una versión nueva" en el `README.md`.

## 0.7.0

- **Playwright sustituye a Chrome DevTools** como MCP de verificación de interfaz. `.mcp.json`
  declara dos servidores con la versión fijada (`@playwright/mcp@0.0.85`) y el Chrome
  instalado (`--browser chrome`, sin descargar Chromium): `playwright` (perfil persistente
  por proyecto, para verificar tu app) y `playwright-taste` (`--isolated`, perfil en memoria,
  para analizar sitios ajenos). `implementer` y `reviewer` usan `playwright`; la vista móvil se
  comprueba con `browser_resize` y el modo oscuro con `browser_emulate_media`.
- `.claude/settings.json`: nuevos `deny` para `browser_run_code_unsafe` (equivale a ejecución
  remota de código, según su documentación) y `browser_file_upload` en ambos servidores.
  Limitación: sin probar que el formato `mcp__playwright__...` bloquee de verdad.
- **Skill `taste`** (`/taste <url>`), copia adaptada de senlindesign/taste-skill (MIT):
  analiza un sitio de referencia y escribe `docs/references/<dominio>/<dominio>.md` y `.json`.
  Solo manual (`disable-model-invocation`), sin exportación (nunca escribe en `CLAUDE.md` ni en
  archivos de otros agentes), sin Python (la comprobación de JSON usa Node) y con las capturas
  ignoradas por git. Los cuatro prompts de análisis y `extract.js` van sin cambios.
- **Skill `sdd-design`**: puerta de entrada del diseño. Jerarquía de fuentes, modos de la
  superficie (Operar, Leer, Persuadir, Experimentar), estructura de `docs/design.md`, reglas de
  movimiento (inspiradas en Emil Kowalski) y lista de anti-patrones (inspirada en Impeccable y
  en taste), todo reescrito y cargado bajo demanda. Se apoya en `frontend-design`.
- **Checkpoint visual:** nueva línea opcional `Checkpoint: visual` en `tasks.md`, solo en la
  primera tarea de cada spec que construya una pantalla nueva (con `Paralelo: no`). El
  `implementer` captura a 375 px y 1280 px, en claro y en oscuro, en
  `specs/NNN-nombre/checkpoint/` (ignorado por git) y el coordinador para siempre, incluso en
  modo continuo o paralelo, para pedirte la aprobación.
- El `planner` lee `sdd-design`, `docs/design.md` y `docs/references/` al redactar "Interfaz"; el
  `reviewer` revisa los RF de interfaz con la lista de anti-patrones.
- `NOTICE.md` con las atribuciones y licencias de terceros.
- README: sección "Diseño de interfaz" reescrita y apartados opcionales, no incluidos, sobre
  Figma (opt-in), Impeccable (con los avisos de seguridad) y Chrome DevTools MCP.
- `.gitignore`: `.playwright-mcp/`, imágenes de `docs/references/` y `specs/*/checkpoint/`.
- Requisitos nuevos: Node 18 o superior (ya necesario), Chrome instalado y aprobar los
  servidores MCP del proyecto la primera vez. Sin probar con un proyecto real.

### Migración desde 0.6.2
1. `.mcp.json`: sustituye `chrome-devtools` por los servidores `playwright` y
   `playwright-taste` de la plantilla (versión fijada). Si el proyecto necesita Lighthouse,
   puede conservar `chrome-devtools` y anotarlo en "Personalizaciones de la plantilla".
2. `.claude/settings.json`: añade a `deny` `mcp__playwright__browser_run_code_unsafe`,
   `mcp__playwright__browser_file_upload`, `mcp__playwright-taste__browser_run_code_unsafe` y
   `mcp__playwright-taste__browser_file_upload`.
3. `.gitignore` (del proyecto): añade `.playwright-mcp/`, `docs/references/**/*.jpeg`,
   `*.jpg`, `*.png` y `specs/*/checkpoint/`.
4. Copia `.claude/skills/sdd-design/`, `.claude/skills/taste/` y `NOTICE.md` de la plantilla.
5. Agentes: en `implementer` y `reviewer`, `mcpServers` pasa de `chrome-devtools` a
   `playwright`, y cada mención de "Chrome DevTools" pasa a Playwright. `implementer`: añade
   la lectura de `sdd-design`, el viñeta de `Checkpoint: visual` y las rutas de capturas en
   la respuesta. `reviewer`: añade la revisión con `anti-patterns.md` en el punto 3 de la
   validación. `planner`: sustituye la lectura de `frontend-design` por la de `sdd-design`,
   `docs/design.md` y `docs/references/`, y añade la regla de `Checkpoint: visual`.
   `sdd-coordinator`: en la fase 5 valida `Checkpoint`, y en las paradas de la fase 6 añade
   la del checkpoint visual; en el preflight, "Playwright" en lugar de "DevTools".
6. Comandos: `sdd-implement` (verificación con Playwright y paso del checkpoint),
   `sdd-validate`, `sdd-plan` (`sdd-design`) y `sdd-tasks` (línea `Checkpoint`).
7. `.claude/skills/sdd/SKILL.md`: párrafo de "Interfaz" del plan, línea `Checkpoint: visual`
   en el formato de tareas, la sección "Checkpoint visual (interfaz)" y el texto del
   preflight.
8. `CLAUDE.md` (del proyecto): en "Verificación" cambia DevTools por Playwright (`browser_resize`
   y `browser_emulate_media`, y la ventana de Playwright para el login) y en "Convenciones" la
   mención de `sdd-design` y `docs/references/`. Si `docs/constitution.md` dice "Chrome DevTools",
   cámbialo por Playwright.
9. `README.md`: la sección "Diseño de interfaz" y los apartados opcionales.
10. Primera vez: aprueba los servidores MCP del proyecto, comprueba que Chrome está instalado
    e inicia sesión de nuevo en la ventana de Playwright (el perfil de DevTools no se
    reutiliza).
11. Actualiza `VERSION` a `0.7.0`.

## 0.6.2

- **La barra de progreso deja de depender solo del modelo.** En la 0.6.1 era una frase
  dentro de un párrafo largo y se podía omitir (varias tareas marcadas en un mensaje y una
  sola barra). Ahora:
  - La línea de cada tarea terminada tiene formato fijo:
    `T3 ✓ <resumen corto> · [███░░░░░░░] 3/10 tareas (30%)`.
  - La barra también se muestra en cada parada y pregunta de la fase 6 y en el último
    mensaje de cada respuesta en modo continuo; si se terminan varias tareas a la vez, una
    línea por tarea y la barra final.
- **Línea de estado de Claude Code** (`statusLine` en `.claude/settings.json`) con el script
  `.claude/scripts/sdd-progress.js`, que lee `specs/*/tasks.md` y muestra, por ejemplo,
  `SDD 001-demo [████░░░░░░] 2/5 (40%) · Lote A 2/3`. Elige la spec en curso más reciente;
  sin spec con tareas pendientes queda vacía. Solo lee, sin dependencias (usa Node).
- Limitación: un `statusLine` en el `settings.json` del proyecto sustituye al que tengas en
  tu configuración de usuario. Para conservar el tuyo, define `statusLine` en
  `.claude/settings.local.json`.

### Migración desde 0.6.1
1. Copia `.claude/scripts/sdd-progress.js` de la plantilla.
2. `.claude/settings.json`: añade
   `"statusLine": {"type": "command", "command": "node .claude/scripts/sdd-progress.js"}`.
   Si el proyecto ya tiene un `statusLine` propio, no lo pises: anótalo en
   "Personalizaciones de la plantilla" de `CLAUDE.md`.
3. `.claude/agents/sdd-coordinator.md`, fase 6: sustituye el párrafo "Informa de cada
   tarea terminada... Barra de progreso" por el de la plantilla (formato fijo y dónde se
   muestra).
4. `.claude/skills/sdd/SKILL.md` (paso 6 de coordinación) y `README.md`: actualiza el texto
   de la barra y menciona la línea de estado.
5. Actualiza `VERSION` a `0.6.2`.

## 0.6.1

- **Barra de progreso de tareas** en el coordinador: tras cada tarea terminada, al cerrar
  cada ola del modo paralelo y al empezar la fase de implementación, muestra una línea como
  `[████░░░░░░] 4/10 tareas (40%)`, con el avance del lote actual y la siguiente tarea si
  hay lotes. Se calcula con Grep sobre `tasks.md` (líneas `- [x]` entre el total), nunca de
  memoria, con 10 casillas redondeadas hacia abajo.
- `/sdd-status` muestra la misma barra y el avance por lote.
- Es por número de tareas, no por tiempo ni esfuerzo; no cuenta las fases fuera de la 6.
- Sin permisos nuevos ni cambios de `settings.json`.

### Migración desde 0.6.0
1. `.claude/agents/sdd-coordinator.md`, fase 6: tras "Informa en una línea de cada tarea
   terminada" añade ", con la barra de progreso" y el párrafo "Barra de progreso" de la
   plantilla; en el modo paralelo, al final del paso f de "No, las integro yo" añade
   "(con la barra de progreso)" (con "Sí, con puertas" ya lo cubre la regla general).
2. `.claude/commands/sdd-status.md`: en el punto 2 añade la barra de progreso.
3. `.claude/skills/sdd/SKILL.md` (paso 6 de coordinación) y `README.md` (paso 5 del
   flujo): menciona la barra.
4. Actualiza `VERSION` a `0.6.1`.

## 0.6.0

- **Agente nuevo `brancher`** que crea la rama de la spec (`spec/NNN-nombre`). Su campo
  `tools` solo permite `git status`, `git rev-parse`, `git branch --list` y
  `git switch -c spec/...`: el permiso queda en la estructura, no en el prompt. Exige estar
  en la rama principal con el árbol limpio; si no, para y lo explica.
- **Fase 0 del coordinador:** al confirmar la carpeta, si estás en la principal con el
  árbol limpio, te propone `spec/NNN-nombre` y, solo con tu sí, llama al `brancher`; después
  comprueba que estás en la rama. Si ya estás en una rama de spec, no pregunta. Si el árbol
  no está limpio o estás en otra rama, pregunta qué hacer.
- `Agent(...)` del coordinador incluye `brancher`. El coordinador sigue sin crear ramas.
- `.claude/settings.json`: se retiran los `deny` de `git switch -c` y `git switch --create`,
  porque los `deny` valen para todos los agentes y bloquearían al `brancher`. Siguen
  bloqueados `-C`, `--force-create`, `-f`, `--force` y `--discard-changes`.
- Limitación: el coordinador conserva `Bash(git switch:*)` para la integración, así que
  que no cree ramas depende de su regla en el prompt; solo el `brancher` lo tiene
  restringido por `tools`. El `implementer` tiene Bash amplio y tampoco queda bloqueado.
- `/sdd-spec` (comando suelto) no crea rama: la rama la gestiona el coordinador.

### Migración desde 0.5.1
1. Copia `.claude/agents/brancher.md` de la plantilla.
2. `.claude/agents/sdd-coordinator.md`: en `tools`, `Agent(planner, reviewer, implementer)`
   pasa a `Agent(planner, reviewer, implementer, brancher)`; sustituye el párrafo "Rama" de
   la fase 0 por el de la plantilla; en la fase 10, paso a, deja "el usuario decide (con
   cambios pendientes, el brancher no puede crear la rama)"; y añade a la regla Git que las
   ramas de spec solo las crea el `brancher`, con el sí del usuario.
3. `.claude/settings.json`: quita de `deny` `Bash(git switch -c:*)` y
   `Bash(git switch --create:*)`. Revisa antes si algún script del proyecto depende de
   ellos. Si tienes un `settings.json` propio, fusiona sin perder lo que haya.
4. `.claude/skills/sdd/SKILL.md`: menciona al `brancher` y añade el paso 0 "Rama" a la
   lista de coordinación. `README.md`: actualiza la lista de agentes, el párrafo de la
   fase 0, la regla de `deny` y la regla de ramas.
5. Actualiza `VERSION` a `0.6.0`.

## 0.5.1

- Nuevo comando `/sync-upstream`, solo para proyectos que son un fork: comprueba el
  remoto `upstream` y el árbol limpio, hace `git fetch upstream` e informa de commits
  por delante y por detrás. Sin commits propios hace `git merge --ff-only`; si hay
  divergencia, no hace merge ni rebase y pregunta. Nunca hace push, reset ni `--force`.
- Declara sus permisos con `allowed-tools` (solo `git remote`, `status`, `fetch upstream`,
  `rev-parse`, `rev-list`, `log` y `merge --ff-only`). Si el proyecto no tiene el remoto
  `upstream`, se detiene sin hacer nada.
- README y `CLAUDE.md` lo mencionan.

### Migración desde 0.5.0
1. Copia `.claude/commands/sync-upstream.md` de la plantilla. Si ya tenías uno propio con
   ese nombre en el proyecto, conserva el tuyo y anótalo en "Personalizaciones de la
   plantilla" de `CLAUDE.md`.
2. `CLAUDE.md` y `README.md`: añade `/sync-upstream` a la lista de comandos (opcional si
   el proyecto no es un fork).
3. Actualiza `VERSION` a `0.5.1`.

## 0.5.0

- **Integración con puertas (opcional, por spec)** en el modo paralelo: si el usuario
  responde "Sí, con puertas", el coordinador integra las ramas de cada ola de una en una
  (`git merge --no-ff --no-commit`), pide al `reviewer` los tests sobre el resultado y
  confirma el merge solo con VERDE; con conflicto o ROJO aborta y para. Después marca las
  tareas con el `planner`, hace un commit solo de `tasks.md` y limpia los worktrees y
  ramas efímeras sin `--force`. Con "No, las integro yo" nada cambia.
- **Commits de lote y de ola sin confirmación (opcional, por spec):** se hacen sin
  AskUserQuestion, con rutas explícitas (`git status --porcelain` filtrado por `Toca`, más
  `tasks.md`) y las mismas comprobaciones de secretos y de verde. El commit de cierre con
  `MEMORY.md`, la integración a la rama principal y cualquier otro borrado siguen pidiendo
  confirmación.
- **Preflight al empezar la implementación:** el coordinador revisa que el comando de tests
  de `CLAUDE.md` no esté pendiente ni lleve `cd`, comprueba DevTools con una verificación
  trivial si alguna tarea lo usa y recuerda servidores y puertos.
- Si un implementer no puede ejecutar los tests en su worktree (dependencias ausentes), el
  coordinador descarta la ola y ejecuta esas tareas en serie.
- `reviewer`: el modo de comprobación de integración corre sobre el árbol de trabajo actual,
  incluso con una fusión sin confirmar, y ejecuta los comandos de tests uno tras otro.
- `.claude/settings.json`: nuevos `deny` para `git worktree remove --force`, `-f` y
  `git worktree add`. Nota: un `deny` por prefijo no cubre los flags al final del comando
  (p. ej. `git worktree remove <ruta> --force`); esa regla queda también en el prompt.
- `.gitignore`: nueva entrada `.claude/worktrees/`.
- `CLAUDE.md`: nota en "Comandos" para escribir el comando de tests sin `cd`.

### Migración desde 0.4.0
1. `.claude/agents/sdd-coordinator.md`, `tools`: añade exactamente
   `Bash(git merge --no-ff --no-commit:*)`, `Bash(git merge --abort:*)`,
   `Bash(git worktree remove:*)` y `Bash(git worktree list:*)`. No añadas push, rebase,
   reset, `git merge` genérico ni `git worktree add`.
2. Fase 6, pregunta del modo: añade, tras elegir el modo, las preguntas "¿Integro yo las
   ramas de cada ola cuando estén verificadas?" (solo en paralelo) y "¿Hago los commits de
   lote y de ola sin pedir confirmación cada vez?" (por defecto No).
3. Fase 6, antes de lanzar la primera tarea: sustituye el recordatorio de servidores por
   el bloque "Preflight" de la plantilla (comando de tests, DevTools, servidores y puertos).
4. Fase 6, bloque "Modo paralelo (por olas)": en el paso c añade el descarte de la ola si
   el implementer no pudo ejecutar los tests en su worktree; sustituye los pasos d, e y f
   por las dos variantes ("Sí, con puertas" y "No, las integro yo"); y en el paso a haz el
   commit parcial sin preguntar si hay consentimiento de commits sin confirmación.
5. Fase 6: añade el párrafo "Commits sin confirmación" tras el de commit por lote, y en la
   parada "Se cierra un lote" la salvedad del consentimiento.
6. Regla Git del coordinador: sustitúyela por la de la plantilla (consentimiento por spec;
   `--no-ff --no-commit` solo en ramas efímeras de la ola; nunca `--force` en
   `git worktree remove`).
7. `.claude/agents/reviewer.md`: actualiza la sección "Si te piden comprobar una
   integración" (corre sobre el árbol actual, incluso con fusión sin confirmar; tests
   uno tras otro).
8. `.claude/settings.json`: añade a `deny` `Bash(git worktree remove --force:*)`,
   `Bash(git worktree remove -f:*)` y `Bash(git worktree add:*)`. Si tienes un
   `settings.json` propio, fusiona sin perder lo que haya.
9. `.gitignore` (es del proyecto, no se sobrescribe): añade a mano `.claude/worktrees/`.
10. `.claude/skills/sdd/SKILL.md`: actualiza "Ejecución paralela (por olas)" (garantía 4
    "Integración con puertas (opcional)", garantía 3 y apartado "Antes de implementar") y
    la regla de git. `README.md`: añade "Dos niveles de autonomía". `CLAUDE.md`: en
    "Comandos", la nota de que el comando de tests va sin `cd`.
11. Actualiza `VERSION` a `0.5.0`.

## 0.4.0

- Nueva fase de **Integración (con confirmación)** en el coordinador, entre Commit y
  Cierre (el Cierre pasa a ser la fase 12): integra la rama de la spec en la principal
  solo con fast-forward y, si el usuario lo elige, la borra.
- Si la rama principal avanzó, el coordinador para: el rebase o el merge lo decide el
  usuario. Nunca hace push; borrar la rama remota es del usuario.
- Opción "Dejar la rama" para quien trabaje con Pull Request.
- Permisos nuevos del coordinador: `git switch`, `git merge-base`,
  `git merge --ff-only` y `git branch -d`. Siguen sin permitirse push, rebase, reset ni
  `git branch -D`.
- Corrección: el commit parcial por lote y por ola ya no pasa por la actualización de
  `MEMORY.md`, que solo se hace al cierre con la spec "implementada".
- `.claude/settings.json`: nuevos `deny` para que las reglas "no crear ramas" y "nunca
  `git branch -D`" no dependan solo del prompt: `git switch` con `-c`, `-C`,
  `--create`, `--force-create`, `-f`, `--force` o `--discard-changes`, y `git branch`
  con `-D`, `-d -f`, `-d --force` o `--force`.

### Migración desde 0.3.0
1. `.claude/agents/sdd-coordinator.md`: añade a `tools` exactamente
   `Bash(git switch:*)`, `Bash(git merge-base:*)`, `Bash(git merge --ff-only:*)` y
   `Bash(git branch -d:*)`. No añadas push, rebase, reset ni `git branch` genérico.
2. En el mismo archivo, inserta la fase "11. Integración (con confirmación)" entre Commit
   y Cierre y renumera el Cierre como fase 12 (copia el texto de la plantilla). Actualiza
   la `description` para incluir la integración.
3. Reglas del coordinador: añade "ni de la 10 a la 11" a la regla de aprobación y, en la
   regla "Git", que el merge solo es `--ff-only` y solo en la fase de Integración, que
   nunca se usa `git branch -D` y que no se toca la rama principal fuera de esa fase. En
   la fase 0, deja "tú no creas ramas".
4. Fase 6, commit parcial por lote: sustituye "el mismo procedimiento de la fase de
   Commit" por "el mismo procedimiento de la fase de Commit, sin su paso b (MEMORY.md
   solo se actualiza al cierre, con la spec 'implementada'), con mensaje 'Spec NNN, lote
   X: ...' y antes de seguir". Si el proyecto ya tiene personalizado este párrafo, el
   cambio ya está hecho.
5. `.claude/skills/sdd/SKILL.md`: añade "Integración" al flujo (lista de fases inicial),
   inserta el paso 11 y renumera el Cierre como 12, y amplía la regla de git. `README.md`:
   añade el paso 8 (Integración) y la regla de `--ff-only`. `CLAUDE.md`: la línea del
   flujo termina en "→ commit → integración".
6. `.claude/settings.json`: añade a `deny` `Bash(git switch -c:*)`,
   `Bash(git switch -C:*)`, `Bash(git switch --create:*)`,
   `Bash(git switch --force-create:*)`, `Bash(git switch -f:*)`,
   `Bash(git switch --force:*)`, `Bash(git switch --discard-changes:*)`,
   `Bash(git branch -D:*)`, `Bash(git branch -d -f:*)`,
   `Bash(git branch -d --force:*)` y `Bash(git branch --force:*)`. Si ya tienes un
   `settings.json` propio, fusiona sin perder lo que haya.
7. Fase 6, paso a de cada ola (modo paralelo): aplica la misma corrección del paso 4 al
   commit parcial "Spec NNN, ola N: ...".
8. Actualiza `VERSION` a `0.4.0`.

## 0.3.0

- Mapa de bloqueos en `tasks.md`: cada tarea declara `Depende de` (tareas anteriores),
  `Toca` (archivos que crea o modifica, con `(compartido)` en lockfiles, configuración
  global, índices de rutas, migraciones y generados) y `Paralelo` (sí o no).
- Si dos tareas tocan el mismo archivo, la posterior depende de la anterior.
- El `planner` genera el mapa; el coordinador lo valida antes de pedir la aprobación de
  las tareas y muestra los niveles como información.
- El `implementer` y `/sdd-implement` comprueban que las dependencias están hechas, y el
  `implementer` indica los archivos que tocó fuera de `Toca`.
- `/sdd-status` muestra qué tareas están listas y cuáles bloqueadas.
- Ejecución paralela por olas, opcional por spec y con un máximo de 2 implementers:
  - Cada implementer trabaja en su worktree y hace commit en una rama efímera.
  - `tasks.md` tiene un solo escritor: el `planner` marca la ola entera tras integrar.
  - El coordinador verifica cada rama contra su `Toca` y descarta la ola si no coincide.
  - El usuario integra las ramas; el `reviewer` comprueba los tests antes de marcar.
  - Antes de cada ola el árbol debe estar limpio (commit parcial con confirmación).

### Migración desde 0.2.0
1. `.claude/skills/sdd/SKILL.md`: en "Tareas (tasks.md)" añade al formato las líneas
   `Depende de:`, `Toca:` y `Paralelo:`, añade los apartados "Mapa de bloqueos" y
   "Ejecución paralela (por olas)" (copia los de la plantilla) y en "Implementación"
   exige que las dependencias estén marcadas `[x]`.
2. `.claude/agents/planner.md`: en "Si te piden las tareas", exige las líneas
   "Depende de:", "Toca:", "Paralelo:" y "Hecho cuando:" y las reglas del mapa; añade la
   sección "Si te piden marcar tareas como hechas (modo paralelo)".
3. `.claude/agents/sdd-coordinator.md`: en la fase 5 añade la validación del mapa (incluido
   "Paralelo") y los niveles en el resumen; en la fase 6 añade la opción "paralelo" a la
   pregunta del modo y el bloque "Modo paralelo (por olas)"; y en las paradas del modo
   continuo usa el campo `Toca` para el alcance de la tarea.
4. `.claude/agents/implementer.md`: comprueba las dependencias, trabaja sobre los archivos
   de `Toca`, informa de los que no estaban en él y añade el punto "Modo paralelo".
5. `.claude/agents/reviewer.md`: añade la sección "Si te piden comprobar una integración
   (modo paralelo)".
6. `.claude/commands/`: `sdd-tasks.md` (formato con las tres líneas nuevas),
   `sdd-implement.md` (comprueba dependencias) y `sdd-status.md` (tareas listas y
   bloqueadas).
7. `CLAUDE.md`: en "Convenciones" añade la línea de ejecución paralela (máximo de
   implementers y recursos compartidos de los tests).
8. Las specs en curso no se tocan: un `tasks.md` sin estos campos se trata como
   secuencial. Solo las specs nuevas llevan el mapa.
9. Actualiza `VERSION` a `0.3.0`.

## 0.2.0

- El `reviewer` ya permite los ejecutores de tests habituales: no hace falta editar el
  agente al empezar un proyecto.
- Nueva sección "Personalizaciones de la plantilla" en `CLAUDE.md` para registrar qué
  archivos de la plantilla se modificaron a propósito.
- README: tabla de propiedad de archivos y pasos para actualizar un proyecto.
- Cada versión se etiqueta con `vX.Y.Z` y lleva su sección Migración.

### Migración desde 0.1.0
1. En `.claude/agents/reviewer.md`, sustituye el comentario `# AJUSTAR…` y la línea `tools`
   por la de la plantilla: añade `Bash(npm test:*)`, `Bash(npm run test:*)`,
   `Bash(pnpm test:*)`, `Bash(yarn test:*)`, `Bash(pytest:*)`,
   `Bash(python -m pytest:*)`, `Bash(dotnet test:*)`, `Bash(go test:*)`,
   `Bash(cargo test:*)`, `Bash(mvn test:*)`, `Bash(gradle test:*)` y
   `Bash(./gradlew test:*)` a lo que ya tenía. Si el proyecto tiene un permiso propio
   (p. ej. `Bash(make test:*)`), consérvalo.
2. En `CLAUDE.md`, antes de "## Memoria", añade la sección "## Personalizaciones de la
   plantilla" y lista ahí lo que el proyecto modificó a propósito (p. ej. el permiso
   propio del paso 1).
3. Actualiza `VERSION` a `0.2.0`.

## 0.1.0

- Flujo SDD completo: constitución, spec, clarificación en bucle, plan, tareas,
  implementación, validación y commit con confirmación.
- Agentes `sdd-coordinator`, `planner`, `reviewer` e `implementer`, y comandos `/sdd-*`.
- Skill `sdd` y skill `frontend-design` (de terceros) conectada al plan de interfaz.
- Tareas en lotes (máximo 10 por lote) y modo continuo con paradas.
- `.gitignore` genérico; las entradas del stack se añaden al definirlo.
- `.claude/settings.json` con reglas `deny` (push, borrados destructivos, lectura de `.env`).
- Versión de `chrome-devtools-mcp` fijada.
- El `planner` actualiza `MEMORY.md` en el modo cierre, con aprobación del usuario.
- El coordinador propone una rama por spec en la fase 0.

### Migración desde la plantilla anterior (sin versión)
1. Crea `.claude/settings.json` con los `deny`: `Bash(git push:*)`,
   `Bash(git reset --hard:*)`, `Bash(git clean:*)`, `Bash(rm -rf:*)`, `Read(./.env)`,
   `Read(./.env.local)` y `Read(./.env.production)`. Si ya existe, fusiona sin perder lo
   que haya. `.gitignore` debe ignorar `.claude/settings.local.json` y no
   `.claude/settings.json`.
2. En `.mcp.json`, cambia `chrome-devtools-mcp@latest` por `chrome-devtools-mcp@1.10.1`.
3. `.claude/agents/planner.md`: añade la excepción de `MEMORY.md` en el modo cierre, la
   sección "Si te piden el cierre (actualizar MEMORY.md)" y el final de "Respuesta"
   adaptado al modo cierre (copia el texto de la plantilla).
4. `.claude/agents/sdd-coordinator.md`: permite `MEMORY.md` en la comprobación de
   `git status` del planner, añade el paso "Rama" a la fase 0, sustituye en la fase de
   Commit los pasos de rama y `MEMORY.md` por la llamada al planner en modo cierre con
   aprobación, y quita del Cierre que `MEMORY.md` se actualiza a mano. Asegúrate de que
   `Bash(git rev-parse:*)` está en `tools`.
5. `.claude/skills/sdd/SKILL.md`: la comprobación del planner admite `MEMORY.md` en modo
   cierre, el paso de Commit menciona al planner, y el criterio de tarea pasa a "una sola
   preocupación y un cambio commiteable" en lugar de minutos.
6. `.claude/commands/sdd-tasks.md`: mismo criterio de tarea.
7. Crea `VERSION` (`0.1.0`), añade la línea de `VERSION` en "Estructura del repo" de
   `CLAUDE.md` y crea un `CHANGELOG.md` (o añade la entrada si ya existe).
