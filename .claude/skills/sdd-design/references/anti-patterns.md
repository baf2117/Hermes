# Señales de interfaz genérica y errores frecuentes

Úsala al diseñar (para evitarlos) y al revisar (como lista de comprobación). Cada punto es
"motivo para mirar de cerca", no veredicto automático: una excepción vale si `docs/design.md`
la justifica o si el usuario la pide. Inspirada en los anti-patrones de Impeccable y en los
análisis de taste (ver `NOTICE.md`), reescrita y resumida.

## Tipografía
- Texto de cuerpo por debajo de ~16 px; interlineado muy ajustado (el cuerpo cómodo ronda 1,5).
- Líneas de texto largo de más de ~75 caracteres; usa `max-width` en `ch`.
- Todo en mayúsculas en párrafos; mayúsculas con espaciado amplio solo en etiquetas cortas.
- Jerarquía plana: tamaños casi iguales para título y cuerpo.
- Familia elegida por inercia (la misma de siempre) sin relación con el producto.
- Titulares con una palabra en cursiva, color o negrita distinto como único recurso.
- Importes y tablas sin cifras tabulares.

## Color
- Gradientes de texto, resplandores o halos decorativos, paleta morado-azul por defecto.
- Texto gris sobre fondo de color; contraste por debajo de AA.
- Grises puros por todas partes (mejor neutros con un leve tinte coherente con el acento).
- Más de un color de acento sin motivo; acento en más del ~20 % de la superficie.
- Color como único portador de significado (estado, error) sin texto ni icono.

## Layout y componentes
- Tarjetas dentro de tarjetas; todo metido en tarjetas idénticas con la misma sombra.
- Rejillas de cuadros decorativos; una métrica grande con etiqueta pequeña y degradado como
  receta de cabecera.
- Numeración decorativa (01 / 02 / 03) en contenido que no es una secuencia.
- Un único radio para todo, sin radio interior menor en elementos anidados.
- Sombras duras desplazadas o efecto cristal sin función.
- Borde lateral grueso de color como decoración de tarjetas; icono en cuadrado redondeado
  sobre cada título; etiqueta superior en mayúsculas sobre cada encabezado.
- Espaciado uniforme que no distingue lo relacionado de lo separado.
- Menús y popovers recortados por su contenedor; scroll horizontal en móvil.

## Interacción y estados
- Sin estado de carga, vacío o error; un error vago o que se disculpa en lugar de explicar.
- Foco invisible; objetivos táctiles pequeños en acciones principales.
- Contenido oculto si falla una animación de entrada.
- Acciones destructivas sin confirmación ni forma de deshacer.
- Un botón que dice "Enviar" donde debería decir qué ocurre ("Guardar cambios"); la misma
  acción con nombres distintos en el mismo flujo.

## Movimiento
Ver `motion.md`. En especial: rebote o elasticidad por defecto, pulsos decorativos, cursores
parpadeantes en texto estático y animación en acciones muy frecuentes.

## Texto
- Frases de marketing vacías ("potencia", "de clase mundial", "sin fricciones").
- Adjetivos sin contenido ("limpio", "moderno", "intuitivo", "elegante") en documentos de
  diseño: sustitúyelos por valores concretos (px, hex, ms) y por la decisión tomada.
- Guion largo en cada frase; el contraste forzado "No es X. Es Y."; texto repetido en un mismo
  contenedor.

## Prueba de genericidad
Para cada principio de diseño escrito, pregúntate: "¿Lo habría podido escribir sin ver este
producto?". Si sí, es relleno: bórralo o sustitúyelo por una decisión con evidencia.
