# Reglas de movimiento

Criterio de partida para decidir si algo se anima y cómo. No son dogmas: una excepción es
válida si `docs/design.md` la justifica. Basadas en las ideas de Emil Kowalski (ver
`NOTICE.md`), reescritas y resumidas.

## 1. ¿Se anima?
Decide por la frecuencia con la que el usuario ve el elemento:

| Frecuencia | Decisión |
|---|---|
| Decenas o cientos de veces al día (atajos, cambio de pestaña, abrir una paleta de comandos, filas de una lista) | Sin animación |
| Varias veces al día (hover, navegación entre vistas) | Mínima o ninguna |
| Ocasional (modales, paneles laterales, avisos) | Animación estándar |
| Rara o primera vez (onboarding, celebraciones) | Se permite algo de personalidad |

Una acción lanzada con teclado no se anima. Se anima solo con un motivo: mantener la
continuidad espacial, indicar un cambio de estado, dar respuesta a una acción, explicar algo
o evitar un salto brusco. "Queda bonito" no basta en elementos que se ven muchas veces.

## 2. Curvas
- Entra o sale de pantalla: **ease-out** (por defecto).
- Se mueve o se transforma dentro de pantalla: **ease-in-out**.
- Cambio de color o hover: **ease**.
- Movimiento constante (barra de progreso, marquesina): **linear**.
- **Nunca ease-in** en interfaz: arranca lento y se siente pesado.
- Curvas de partida: `cubic-bezier(0.23, 1, 0.32, 1)` (salida fuerte) y
  `cubic-bezier(0.77, 0, 0.175, 1)` (entrada y salida). Defínelas como variables CSS una vez.

## 3. Duraciones
- Respuesta de un botón: 100–160 ms.
- Tooltips y popovers pequeños: 125–200 ms.
- Menús desplegables y selectores: 150–250 ms.
- Modales y paneles: 200–300 ms (hasta 500 ms solo con justificación).
- Regla general: la interfaz no pasa de 300 ms sin motivo.
- Las salidas, algo más rápidas que las entradas (~20 %). La duración crece con la distancia.
- Varios elementos que entran juntos: escalonado de 30–80 ms, nunca todos a la vez.

## 4. Forma del movimiento
- No entres desde `scale(0)`: usa `scale(0.95)` con `opacity: 0`.
- Pulsación de botón: `scale(0.97)` en `:active` (rango 0,95–0,98).
- Popovers, menús y tooltips crecen desde su origen: `transform-origin` en el elemento que
  los dispara. Los modales, desde el centro.
- Para entradas sin JavaScript, `@starting-style` donde el navegador lo soporte; si no, un
  atributo de estado montado.
- Transiciones, no keyframes, para lo que puede interrumpirse (avisos, interruptores): una
  transición retoma desde donde está; un keyframe reinicia.
- Resortes solo para gestos (arrastrar, deslizar); rebote entre 0,1 y 0,3, o ninguno.

## 5. Rendimiento
- Anima solo `transform` y `opacity`. Evita animar `width`, `height`, `margin`, `padding`,
  `top` o `left` (excepción razonada: la altura medida de un acordeón).
- Nunca `transition: all`: lista las propiedades.
- Un `blur` para disimular un fundido, por debajo de 20 px.

## 6. Accesibilidad
- Respeta `prefers-reduced-motion`: conserva `opacity` y color y quita el desplazamiento y la
  escala. "Menos y más suave", no "cero".
- `hover` solo en punteros precisos: `@media (hover: hover) and (pointer: fine)`; en táctil
  el toque dispara un hover falso.
- Si falla una animación de entrada, el contenido debe quedar visible.

## 7. Lista de revisión (para el `reviewer`)
Cada hallazgo con `archivo:línea`. Es incumplimiento si hay:
`transition: all`, entrada desde `scale(0)`, `ease-in` en interfaz, `transform-origin` en
el centro de un popover anclado, animación en una acción con teclado o de uso muy frecuente,
duración mayor de 300 ms sin motivo, `hover` sin la condición de puntero, keyframes en un
elemento que debe poder interrumpirse, propiedades de layout animadas sin excepción
justificada, entrada y salida con la misma velocidad, varios elementos sin escalonar, falta de
`prefers-reduced-motion`.
Formato de respuesta: una tabla Antes / Después / Por qué, y veredicto Aprobado o Cambios.
