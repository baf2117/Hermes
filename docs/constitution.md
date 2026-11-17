# Constitución

<!-- PLANTILLA: sustituye estos principios de ejemplo con /sdd-constitution y borra este
comentario. Máximo 15 líneas, cortos y verificables. Mientras diga "PLANTILLA", el
coordinador te avisará de que falta rellenarla. -->

1. **Stack cerrado.** Solo el stack de `CLAUDE.md`. Una dependencia o servicio nuevo requiere aprobación y una nota en `docs/ARCHITECTURE.md`.
2. **La spec manda.** Todo cambio de comportamiento se describe antes en `specs/NNN-nombre/spec.md`. Si código y spec difieren, se corrige uno de los dos en el mismo cambio.
3. **Lógica separada de la interfaz.** Reglas, validación y acceso a datos viven en [capa de lógica]; la interfaz solo presenta y llama.
4. **Tests.** Toda lógica nueva lleva test y el comando de tests queda en verde. La interfaz se verifica con Playwright.
5. **Datos protegidos.** Ningún dato personal ni secreto en repo, logs, tests ni prompts: solo datos ficticios.
6. **Idioma.** [Idioma del código, de los comentarios y de la interfaz.]

**Deudas conocidas (aceptadas por ahora):** [ninguna].
