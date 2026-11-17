# Estructura de `docs/design.md`

Es la fuente de verdad del diseño del proyecto. Se crea en la primera tarea de interfaz, a
partir del diseño aprobado en el plan, y se actualiza solo con aprobación del usuario (un
cambio de diseño pasa por `/sdd-change`). Máximo ~120 líneas, con valores concretos (px,
hex, ms), sin adjetivos vacíos ("limpio", "moderno").

```markdown
# Diseño

Estado: borrador | aprobado · Última revisión: AAAA-MM-DD

## Contexto
- **Modo:** Operar | Leer | Persuadir | Experimentar (ver la skill sdd-design)
- **Plataforma:** web | móvil | adaptable
- **Usuarios y entorno:** quién lo usa, con qué dispositivo y en qué condiciones (p. ej.
  mostrador con pantalla táctil, oficina con teclado)
- **Propósito:** qué hace mejor esta interfaz que la alternativa

## Principios (3 a 5)
Cada uno con la decisión y lo que se rechaza: "Densidad media: filas de 40 px, se acepta
más scroll a cambio de objetivos táctiles cómodos".

## Color
Tabla de tokens: nombre, hex y uso. Neutros con tinte (indica el matiz) o grises puros.
Un único color de acento y dónde se permite. Pares de contraste comprobados.

## Tipografía
Familias y roles (títulos, cuerpo, números). Escala con tamaños, pesos e interlineado.
Cifras tabulares en importes y tablas. Medida de línea para texto largo.

## Espaciado y layout
Unidad base (4 u 8 px), escala permitida, ancho máximo del contenido, rejilla y puntos de
corte. Qué se agrupa por proximidad y qué por contenedor.

## Forma
Radios por tipo de componente (y el radio interno de los anidados), sombras y bordes.

## Movimiento
Política: qué se anima y qué no, curvas y duraciones permitidas, comportamiento con
`prefers-reduced-motion`. En modo Operar, sin animación en acciones muy frecuentes.

## Componentes clave
Los 5 a 10 componentes que se repiten (botón, campo, tabla, modal, aviso…), con sus estados
(reposo, foco, activo, deshabilitado, carga, error).

## Accesibilidad
Contraste objetivo, foco visible, objetivos táctiles mínimos, teclado.

## Referencias
Enlaces a `docs/references/<dominio>/` usados y qué se tomó de cada uno (principio, no copia).

## Anti-patrones del proyecto
Lo que este proyecto decide no hacer, además de la lista general.
```
