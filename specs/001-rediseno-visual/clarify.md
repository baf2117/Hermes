# Clarificación — Spec 001

## Ronda 1 (2026-11-17)

28 detecciones (10 altas, 14 medias, 4 bajas)

## C-01 · Tema negro y dorado de «En vivo» sin decidir
- Categoría: 1
- Severidad: Alta
- Dónde: RF-9, Dudas abiertas (1.ª), Casos límite (último), RF-34
- Detección: RF-9 solo dice que se aplicará «la decisión que se tome», así que no se puede verificar. Hoy `body` lleva siempre la clase `stage` (hermes/status.py:901) y sus reglas (status.py:463-475) tapan las paletas clara y oscura (status.py:242-261). Mientras no se decida, RF-5, RF-6, RF-8 y RF-34 tampoco se pueden comprobar.
- Estado: resuelta
- Decisión: se retira del todo el tema negro y dorado, también en la vista En vivo; todas las vistas toman la paleta nueva en claro y en oscuro (RF-5, RF-6, RF-9).

## C-02 · Escala tipográfica «corta» sin número máximo
- Categoría: 1
- Severidad: Alta
- Dónde: RF-11, Dudas abiertas (4.ª)
- Detección: «Corta» no es medible y el número máximo de tamaños queda «por decidir». Así, RF-11 solo comprueba que se respeta una escala que todavía no tiene límite.
- Estado: resuelta
- Decisión: escala de máximo 5 tamaños (por ejemplo 13/14/16/20/24 px) (RF-11).

## C-03 · Criterio de «anti-patrón sin justificar» y lista de referencia
- Categoría: 1
- Severidad: Alta
- Dónde: Criterios de finalización (4.º), RF-4, Definiciones («Anti-patrón»), Dudas abiertas (3.ª)
- Detección: No está claro si una excepción queda justificada con estar escrita en `docs/design.md` o si además debe aprobarla el usuario. Tampoco está claro qué lista manda: la de la skill o la del proyecto, que deriva de ella. El criterio de finalización no se puede verificar.
- Estado: resuelta
- Decisión: manda la lista de `docs/design.md` (parte de la de la skill y puede ampliarla); una excepción vale solo si está escrita con su motivo y el usuario la aprueba (Definiciones, RF-4, Criterios).

## C-04 · Colores con significado frente a acento único
- Categoría: 2
- Severidad: Alta
- Dónde: RF-8, RF-20, Definiciones («Colores con significado»), Casos límite (colores de categoría y urgencia), Dudas abiertas (5.ª)
- Detección: RF-8 permite cualquier color «con significado» enumerado, sin límite. Así, el acento único se puede vaciar con 8 colores de categoría y 3 de urgencia (status.py:245-247). Sin la decisión, no se puede verificar RF-8 ni el caso límite «no se confunden con el acento».
- Estado: resuelta
- Decisión: un solo acento (acción principal, selección y foco); juego cerrado de colores de estado (éxito, aviso, peligro); las 8 categorías conservan color propio en tonos atenuados, nunca en botones ni foco (Definiciones, RF-8).

## C-05 · Vistas fuera de alcance: ¿paleta nueva o estilo actual?
- Categoría: 2
- Severidad: Alta
- Dónde: RF-34, Fuera de alcance (4.º), Dudas abiertas (8.ª)
- Detección: RF-34 exige AA y cero desplazamiento horizontal en claro y en oscuro en Apuntes, Consumo, Historial, En vivo y Ajustes. Esas vistas hoy dependen del tema `stage`, y cumplirlo en ambos modos puede obligar a retocarlas, lo que choca con que su rediseño quede fuera. Tampoco se sabe si heredan la tipografía y la paleta nuevas a través del marco.
- Estado: resuelta
- Decisión: heredan paleta y tipografía del marco, con solo los retoques mínimos para AA y sin desplazamiento horizontal de página, sin rediseñarlas (RF-34, Fuera de alcance).

## C-06 · RF-20 permite señales de texto nuevas y RF-32 prohíbe textos nuevos
- Categoría: 2
- Severidad: Alta
- Dónde: RF-20, RF-32, RF-22, RF-23
- Detección: RF-20 acepta «texto» como señal no cromática de urgente o vencida, pero RF-32 obliga a conservar los mismos textos visibles. No se sabe si añadir una etiqueta como «Vencida» incumple RF-32.
- Estado: resuelta
- Decisión: no se añaden textos visibles nuevos; urgente y vencida se señalan con color más icono o peso, usando los textos existentes (RF-20).

## C-07 · Estado de carga nuevo frente a «sin cambiar lo que hace»
- Categoría: 2
- Severidad: Alta
- Dónde: RF-21, RF-32, HU-7
- Detección: RF-21 pide un estado de carga «definido en design.md» sin decir si ya existe uno hoy ni con qué texto. Si hoy no existe o no tiene texto, crearlo choca con RF-32 (mismos textos) y con el objetivo de no cambiar el comportamiento.
- Estado: resuelta
- Decisión: se permite un estado de carga sin texto visible nuevo, anunciado solo a lectores de pantalla, como excepción enumerada en RF-32 (RF-21, RF-32).

## C-08 · Desplazamiento horizontal: RF-24 frente a pestañas y filtros
- Categoría: 2
- Severidad: Alta
- Dónde: RF-24, Casos límite (pestañas y filtros)
- Detección: RF-24 prohíbe el desplazamiento horizontal «en el marco», pero los casos límite solo exigen que la página entera no se desplace. Hoy las pestañas se desplazan por dentro (`.tabs` con `overflow-x:auto`, status.py:272). No se sabe si el desplazamiento interno de pestañas, subpestañas o filtros está permitido. Tampoco si «no recortará textos» prohíbe los puntos suspensivos en títulos largos.
- Estado: resuelta
- Decisión: la página nunca se desplaza en horizontal; pestañas, subpestañas y filtros sí pueden desplazarse por dentro; los títulos largos pueden cortarse con puntos suspensivos (una o dos líneas) y se ven completos al abrir la tarea (RF-24).

## C-09 · RF de marco y Tareas que solo remiten a «según docs/design.md»
- Categoría: 1
- Severidad: Alta
- Dónde: RF-14, RF-15, RF-16, RF-17, RF-18, RF-19, RF-21, RF-31
- Detección: Su único criterio es «según `docs/design.md`», un documento que todavía no existe y que se aprobará después. La spec no fija qué partes del documento hacen verificables estos RF ni cómo se comprueba la conformidad (valores declarados en el CSS, valores calculados en el navegador o revisión visual).
- Estado: resuelta
- Decisión: `docs/design.md` fija tokens con nombre y el estilo del marco y Tareas solo los usa, comprobado por un test; la comprobación en el navegador mide contraste, 44 px y desplazamiento a 375 y 1280 px en claro y oscuro (RF-39, RNF-6, RNF-7).

## C-10 · Qué cuenta como «urgente», «vencida» y «pendiente»
- Categoría: 1
- Severidad: Alta
- Dónde: RF-20, HU-5, Definiciones
- Detección: Faltan las definiciones de urgente (¿prioridad alta?, ¿fecha próxima?) y de vencida. HU-5 pide distinguir también «lo pendiente», pero ningún RF lo cubre.
- Estado: resuelta
- Decisión: urgente = urgencia «alta»; vencida = su fecha límite (o, si no tiene, la de aviso) ya pasó; pendiente = no terminada. Nuevo RF-35 (HU-5) para distinguir pendiente de terminada.

## C-11 · Tipografía del sistema o propia
- Categoría: 1
- Severidad: Media
- Dónde: RNF-2, RF-10, RF-11, Dudas abiertas (2.ª)
- Detección: La decisión está sin tomar. Si se elige una tipografía propia, sería un recurso nuevo que exige aprobación previa (constitución, principio 1; CLAUDE.md «Pregunta antes»). La spec no recoge en ningún RF qué pasa si falla la carga del archivo local.
- Estado: resuelta
- Decisión: tipografía propia servida en local; permiso previo con nombre, origen, licencia y tamaño (lo pide el plan); nuevo RF-36: si no carga, se usa la del sistema sin romper el diseño; nada externo en tiempo de ejecución (RNF-1, RNF-2).

## C-12 · Claro/oscuro: solo el sistema o también un selector manual
- Categoría: 4
- Severidad: Media
- Dónde: RF-5, RF-6, RF-7, Dudas abiertas (6.ª)
- Detección: La decisión está sin tomar. Un selector manual sería un ajuste o función nuevo: según la constitución (principio 3) y CLAUDE.md iría en Ajustes y guardaría una preferencia. Eso choca con «mismos datos guardados» (RF-32) y con dejar Ajustes fuera de alcance.
- Estado: fuera de alcance
- Decisión: claro/oscuro solo sigue al sistema operativo; el selector manual queda fuera de alcance (posible spec posterior).

## C-13 · Área táctil de 44 px: dónde aplica y a qué controles
- Categoría: 1
- Severidad: Media
- Dónde: RF-25, Dudas abiertas (7.ª)
- Detección: «En dispositivos táctiles y a 375 px» no aclara si las condiciones son acumulativas o alternativas. Tampoco dice si aplica con ratón ni si incluye controles densos dentro de las tarjetas (casillas, enlaces dentro del texto, contadores). La skill solo lo exige en las acciones principales.
- Estado: resuelta
- Decisión: 44×44 px para los controles que se pulsan con puntero táctil o a 375 px; con ratón en la laptop, mínimo 32 px; enlaces dentro de un texto exentos (RF-25).

## C-14 · RF-29 añadido sin que lo pidiera el usuario y con excepción ambigua
- Categoría: 2
- Severidad: Media
- Dónde: RF-29, HU-6, RF-32
- Detección: La petición era un rediseño visual sin cambio de comportamiento. RF-29 añade comportamiento de foco y de cierre, así que choca con HU-7 y RF-32. Además, «salvo que hoy no se permita» no dice qué diálogos son la excepción; el de confirmación ya se cierra con Escape (status.py:1208).
- Estado: resuelta
- Decisión: RF-29 se queda sin la excepción ambigua (foco atrapado y devuelto y cierre con Escape en todos los diálogos), como excepción de accesibilidad enumerada en RF-32.

## C-15 · «Logo e íconos» añadido a Fuera de alcance sin que lo pidiera el usuario, y ambiguo
- Categoría: 2
- Severidad: Media
- Dónde: Fuera de alcance (5.º), RF-14 (marca), RF-18 (botón de icono), RF-20 (icono)
- Detección: La petición no lo excluía. No se sabe si «íconos» son solo los de la app instalada o también los de la interfaz. Si son también los de la interfaz, choca con RF-18 y RF-20, que usan iconos, y con la marca de la cabecera (`.brand-dot`, que usa el acento).
- Estado: resuelta
- Decisión: fuera de alcance solo el logo y los iconos de la app instalada; los iconos de la interfaz y la marca de la cabecera forman parte del marco (Definiciones, Fuera de alcance).

## C-16 · Botón de hablar y panel de voz sin ubicar en el alcance
- Categoría: 3
- Severidad: Media
- Dónde: Definiciones («Marco»), RF-16, RF-30
- Detección: RF-16 cita el botón de hablar, pero ni él ni el panel de voz (status.py:831-857, con animación al grabar) entran en la definición de marco ni en la de vista Tareas. No se sabe si se rediseñan ni si les aplican RF-25, RF-27, RF-30 y RF-31.
- Estado: resuelta
- Decisión: el botón de hablar y el panel de voz forman parte del marco y siguen `docs/design.md`; les aplican foco, área táctil, contraste y movimiento (Definiciones, nuevo RF-38, RF-30).

## C-17 · «Texto de cuerpo» de 16 px sin delimitar
- Categoría: 1
- Severidad: Media
- Dónde: RF-10
- Detección: No se define qué texto es «cuerpo» frente a metadatos, chips, contadores o etiquetas, que hoy van a 13-14 px. Tampoco se dice si los campos de entrada cuentan como cuerpo; en Safari del iPhone, por debajo de 16 px el campo provoca zoom.
- Estado: resuelta
- Decisión: cuerpo de 16 px = texto de las tareas, párrafos, avisos y todos los campos de entrada; metadatos, chips y contadores pueden ir a 13-14 px (Definiciones, RF-10).

## C-18 · «Acción principal de la pantalla» indefinida
- Categoría: 1
- Severidad: Media
- Dónde: RF-16
- Detección: No se define cuál es la acción principal de cada pantalla, así que no se puede comprobar que el aviso no la tape. Tampoco se cubre el aviso con el teclado virtual abierto, que sí aparece en los casos límite.
- Estado: resuelta
- Decisión: acción principal = la caja de escribir/hablar de la página y el botón Guardar de cada diálogo; los avisos nunca la tapan, tampoco con el teclado virtual abierto (Definiciones, RF-16).

## C-19 · Diálogo a 375×812: «visible sin desplazar» frente a «alcanzable» con el teclado abierto
- Categoría: 2
- Severidad: Media
- Dónde: RF-17, Casos límite (editor con teclado virtual)
- Detección: RF-17 exige la acción principal visible sin desplazar, y el caso límite solo pide que sea «alcanzable» con el teclado abierto. No queda claro qué criterio vale en cada situación, ni si la foto del recibo (que pertenece a Consumo) tiene acción principal.
- Estado: resuelta
- Decisión: a 375×812, Guardar visible sin desplazar con el teclado cerrado y alcanzable con él abierto (RF-17). Queda una duda abierta sobre la acción principal de los diálogos sin Guardar (confirmación y foto de recibo).

## C-20 · Contraste de los controles desactivados
- Categoría: 2
- Severidad: Media
- Dónde: RF-18, RF-27
- Detección: RF-27 exige 3:1 en bordes de controles e iconos sin excepciones, y RF-18 define un estado desactivado. No se dice si los desactivados quedan exentos, como permite WCAG, ni qué umbral se usa para «texto grande».
- Estado: resuelta
- Decisión: los controles desactivados quedan exentos del contraste, como permite WCAG, pero deben verse claramente como no disponibles; «texto grande» se define según WCAG (RF-27, Definiciones).

## C-21 · Zonas seguras sin método de verificación
- Categoría: 1
- Severidad: Media
- Dónde: RF-26, RNF-4
- Detección: RF-26 depende de que la página corra como app instalada en el iPhone. La verificación prevista (Playwright en local, RNF-4) no reproduce ese estado ni la muesca, y la spec no dice cómo se comprueba.
- Estado: resuelta
- Decisión: las zonas seguras las comprueba a mano el usuario en su iPhone, como criterio de finalización.

## C-22 · Casos límite sin resultado esperado
- Categoría: 3
- Severidad: Media
- Dónde: Casos límite (barra de estado y color de tema en claro; lista vacía, muchas tareas y vista Calendario; zoom al 200 %)
- Detección: Varios casos solo se enumeran, sin decir qué debe pasar, y ningún RF los cubre. Hoy `theme-color` y la barra de estado están fijados en negro (status.py:230 y 239). Tampoco queda claro si la vista Calendario forma parte de la vista Tareas o solo su selector.
- Estado: resuelta
- Decisión: el color de tema y la barra de estado siguen al modo claro/oscuro (nuevo RF-41); la vista Calendario entra como parte de Tareas; lista vacía, muchas tareas y zoom al 200 % sin solapes ni desplazamiento horizontal de página (nuevo RF-40, Casos límite).

## C-23 · Excepciones que surgen después de aprobar docs/design.md
- Categoría: 3
- Severidad: Media
- Dónde: RF-4, Criterios de finalización (1.º y 4.º)
- Detección: `docs/design.md` se aprueba al principio, pero RF-4 exige registrar las excepciones que aparezcan al implementar. No se dice si cada excepción nueva requiere volver a aprobar el documento.
- Estado: resuelta
- Decisión: las excepciones nuevas que surjan al implementar se enseñan al usuario y se aprueban una a una, sin reaprobar el documento entero (RF-4).

## C-24 · Cómo se verifica que «textos y funciones no cambiaron»
- Categoría: 1
- Severidad: Media
- Dónde: RF-32, RF-33, Criterios de finalización (5.º)
- Detección: Ningún test actual comprueba los textos ni los identificadores de la página: solo hay 2 coincidencias en tests/test_v2.py. La spec no fija el método para demostrar que no hubo regresión (comparar textos, recorrer las funciones con Playwright u otro).
- Estado: resuelta
- Decisión: un test compara los textos visibles y los identificadores y clases que usa el script antes y después (RNF-8, Criterios).

## C-25 · El acento en el indicador de conexión
- Categoría: 2
- Severidad: Baja
- Dónde: Definiciones («Acento»), RF-8, RF-14
- Detección: El acento se reserva para la acción principal, la selección y el foco. Hoy el indicador de conexión también lo usa para «conectado» (status.py:278), lo que según la definición sería un significado de estado, y no se dice qué rol le toca.
- Estado: resuelta
- Decisión: el indicador de conexión usa los colores de estado (conectado/desconectado), no el acento (RF-14, Definiciones).

## C-26 · «Importes» y «cifras que se comparan» en el marco y en Tareas
- Categoría: 1
- Severidad: Baja
- Dónde: RF-12
- Detección: No se dice qué importes hay en el marco o en la vista Tareas. «Cifras que se comparan entre sí» es abierto fuera del mínimo de los contadores.
- Estado: resuelta
- Decisión: cifras tabulares en los cinco contadores (Pendientes, Urgentes, Vencidas, Para hoy, Terminadas), en los números de día del Calendario y en cualquier importe del marco o de Tareas (RF-12).

## C-27 · Contraste «frente al fondo sobre el que se usa» y ausencia de referencias
- Categoría: 3
- Severidad: Baja
- Dónde: RF-2, RF-3
- Detección: Un mismo color se usa sobre varios fondos (página, tarjeta, superficie suave) y no se dice cuál medir o si deben medirse todos. RF-3 no prevé el caso de que no se analice ninguna referencia.
- Estado: resuelta
- Decisión: el contraste se mide sobre cada fondo donde se usa el color (página, tarjeta, superficie suave); si no se analiza ninguna referencia, RF-3 se cumple indicando «sin referencias» (RF-2, RF-3, RF-27).

## C-28 · Nombres de archivo en la spec y sin requisito para 1280 px
- Categoría: 1
- Severidad: Baja
- Dónde: RF-1 a RF-4, RNF-4, Criterios de finalización (3.º)
- Detección: La plantilla pide que la spec no nombre archivos; aquí `docs/design.md` aparece en la mayoría de los RF, aunque lo pidió el usuario. El checkpoint se hace a 1280 px, pero ningún RF dice cómo debe verse la página en la laptop.
- Estado: aceptada
- Decisión: se acepta nombrar `docs/design.md` porque es un entregable pedido por el usuario; la otra mitad se resuelve con el nuevo RF-37 (ancho máximo legible a 1280 px, sin estirar el contenido) y RF-24 a 1280 px.

Totales: 10 altas, 14 medias, 4 bajas.
Resultado de la ronda 1: 26 resueltas, 1 aceptada (C-28, resuelta además en su otra mitad), 1 fuera de alcance (C-12).

Duda surgida al aplicar C-18/C-19 — resuelta: la acción principal del diálogo de confirmación es su botón de confirmar y la del diálogo de foto de recibo, su botón de cerrar; les aplican las mismas reglas que a Guardar (visible sin desplazar a 375×812 con el teclado cerrado, alcanzable con él abierto y sin que los avisos la tapen). Actualizados la definición de «Acción principal», RF-16 y RF-17; quitada de «Dudas abiertas».

## Ronda 2 (2026-11-17)

11 detecciones (2 altas, 5 medias, 4 bajas)

Las 28 decisiones de la ronda 1 están en la spec. Las 7 HU tienen al menos un RF y todos los RF citan una HU. Las detecciones de abajo vienen de contrastar la spec con lo que hace hoy `hermes/status.py`, o de que dos partes de la spec chocan entre sí.

## C-29 · La tipografía propia choca con la seguridad de la página y con «mismas rutas»
- Categoría: 2
- Severidad: Alta
- Dónde: RNF-1, RNF-2, RF-36, RF-32, Fuera de alcance (2.º)
- Detección: La política de seguridad de la página es `default-src 'none'` y no tiene `font-src` (hermes/status.py:3332). Por eso hoy no se puede cargar ninguna fuente, ni local ni en `data:`. Servirla desde los recursos de Hermes (RNF-2) exige cambiar esa política y añadir una ruta nueva. Pero la política queda fuera de alcance, RF-32 exige «mismas rutas» y CLAUDE.md prohíbe tocar la seguridad de `status.py` sin una spec que lo diga.
- Estado: resuelta
- Decisión: se mantiene la tipografía propia servida en local; como excepción explícita entra un cambio mínimo de la política para permitir fuentes solo del propio origen y una ruta nueva solo para los archivos de fuente; token, Host, Origin y el resto de la política no cambian. Sigue el permiso previo de descarga y RF-36 (nuevo RF-48; RF-32, RNF-2, Fuera de alcance y Criterios).

## C-30 · Las categorías y sus colores los elige el usuario: no son 8 colores fijos de la paleta
- Categoría: 2
- Severidad: Alta
- Dónde: Definiciones («Colores de categoría»), RF-8, RF-27, RF-39, RF-32, Casos límite (colores de categoría)
- Detección: Las categorías se configuran y el usuario elige su color en Ajustes, un solo color para claro y oscuro (`HERMES_CATEGORY_COLORS`, hermes/settings.py:75; status.py:1320, 3069 y 3098). Cada categoría nueva nace con un color propio. Así, no se puede verificar que solo se usen colores enumerados en `docs/design.md` (RF-8, RF-39) ni que se cumpla el contraste (RF-27). Quitar esa función iría contra RF-32.
- Estado: resuelta
- Decisión: el color elegido en Ajustes se sigue guardando igual; la página lo usa solo como punto o borde pequeño y genera al pintar una variante atenuada para claro y otra para oscuro; el texto de la categoría va en neutro. RF-8/RF-39 se verifican sobre esa regla de derivación, no sobre una lista fija (Definiciones, RF-2, RF-8, RF-27, RF-39, Casos límite).

## C-31 · Las urgencias «Normal» y «Baja» no tienen color en el juego cerrado
- Categoría: 3
- Severidad: Media
- Dónde: Definiciones («Colores de estado»), RF-8, RF-20
- Detección: Hoy cada tarjeta lleva un punto de urgencia y el editor un selector, ambos con un color por cada urgencia (`--u-alta`, `--u-media` y `--u-baja`; status.py:245, 1135 y 1396). La spec solo asigna color a «urgente» (peligro). No dice qué color llevan «Normal» y «Baja», que no son éxito, aviso ni peligro, ni si dejan de tenerlo.
- Estado: resuelta
- Decisión: Urgente = color de estado peligro; Normal y Baja = neutros (Baja más tenue), distinguidos también por su texto (Definiciones «Urgencia», RF-8, Casos límite).

## C-32 · «Nunca en botones» frente a los filtros por categoría, que son botones con su punto de color
- Categoría: 1
- Severidad: Media
- Dónde: RF-8, Definiciones («Vista Tareas»: filtros por categoría)
- Detección: Los filtros por categoría son botones que llevan dentro un punto con el color de la categoría (status.py:1563). El selector de categoría hace lo mismo (status.py:1595). No se sabe si un punto dentro de un botón cuenta como «usar el color en botones», así que RF-8 no se puede verificar en esos controles.
- Estado: resuelta
- Decisión: el punto de color de categoría dentro de un filtro o del selector está permitido; lo prohibido es que el color de categoría sea fondo, borde o texto de un botón (RF-8).

## C-33 · El test de RNF-8 falla con cualquier cambio de nombre que RF-33 permite
- Categoría: 2
- Severidad: Media
- Dónde: RNF-8, RF-33
- Detección: RF-33 permite cambiar el nombre de identificadores y clases si se cambian en todos sus usos. RNF-8 exige un test que compare esos identificadores y clases antes y después del cambio, así que cualquier cambio de nombre permitido lo pondría en rojo. Tampoco se dice si «textos visibles» incluye los que genera el script, como los textos de los estados vacíos (status.py:1309-1311) o «Vencida · …».
- Estado: resuelta
- Decisión: el test compara contra una lista de referencia de textos visibles e id/clases; cada cambio de nombre permitido se registra en una tabla «antes → después» (la hace el plan) y el test comprueba que el nombre viejo ya no aparece en ningún uso; los textos que genera el script cuentan como visibles (Definiciones «Textos visibles», RF-33, RNF-8).

## C-34 · No está claro qué estilo es «del marco y de la vista Tareas»
- Categoría: 1
- Severidad: Media
- Dónde: RF-11, RF-13, RF-39, RNF-6
- Detección: Las otras vistas usan también varias reglas del marco y de Tareas, como `body`, `.empty`, `.undo`, `.primary` o `.icon-btn` (por ejemplo, `.empty` en status.py:1096, 1107 y 1949). La spec no define si esas reglas compartidas cuentan como estilo del marco o de Tareas. Sin ese límite, el test de tokens de RNF-6 no tiene un alcance comprobable.
- Estado: resuelta
- Decisión: las reglas compartidas por varias vistas cuentan como marco y usan tokens; con el nuevo alcance, todo el estilo de la página entra en el test de tokens (Definiciones «Marco», RF-39, RNF-6).

## C-35 · RF-34 no tiene verificación, y su alcance choca con el de RF-24
- Categoría: 1
- Severidad: Media
- Dónde: RF-34, RF-24, RNF-7, Criterios de finalización (7.º)
- Detección: RNF-7 solo mide RF-24, RF-25 y RF-27, y RF-27 se limita al marco y a Tareas. El criterio que cita RF-34 solo habla de que «no cambiaron». Ninguna comprobación cubre el contraste AA ni el desplazamiento horizontal de las vistas fuera de alcance en claro y en oscuro. Además, RF-24 habla de «la página» a 375 y a 1280 px, mientras que RF-34 pide esas vistas solo a 375 px. No se sabe si deben cumplir también a 1280 px.
- Estado: resuelta
- Decisión: cambio de alcance pedido por el usuario («quiero que todo se cambie no solo tareas»): la spec cubre el marco y todas las vistas, rediseñadas a fondo según `docs/design.md` y entregables por partes; todas se miden igual (AA, 44 px, sin scroll horizontal de página a 375 y 1280 px, claro y oscuro, tokens) (Objetivo, nueva HU-8, Definiciones «Vistas», RF-34 reescrito, nuevos RF-42 a RF-47, RNF-4, RNF-6, RNF-7, Fuera de alcance, Criterios).

## C-36 · Las zonas seguras dejan fuera el botón de hablar y el panel de voz
- Categoría: 3
- Severidad: Baja
- Dónde: RF-26, Definiciones («Marco»)
- Detección: RF-26 solo nombra la cabecera, los avisos y los diálogos. El botón de hablar y el panel de voz son parte del marco, van fijos abajo junto a la barra de inicio y hoy respetan las zonas seguras (status.py:831 y 846). La spec no exige que lo sigan haciendo, y tampoco nombra el margen inferior del contenido (status.py:529).
- Estado: resuelta
- Decisión: RF-26 incluye también el botón de hablar, el panel de voz y el margen inferior del contenido, como hoy (RF-26).

## C-37 · Barra de estado y color de tema cuando el modo cambia con la app abierta
- Categoría: 3
- Severidad: Baja
- Dónde: RF-41, RF-7, Casos límite (app instalada en modo claro)
- Detección: RF-7 exige aplicar el cambio de claro a oscuro sin recargar. RF-41 no dice si el color de tema y la barra de estado del iPhone deben cambiar también al momento o basta con que acierten al abrir la app, así que la prueba manual del criterio de finalización no tiene un resultado esperado definido.
- Estado: resuelta
- Decisión: si el modo cambia con la app abierta, el color de tema cambia al momento; para la barra de estado del iPhone basta con que acierte al abrir la app (RF-41, Casos límite, Criterios).

## C-38 · Estado de carga «solo para lectores de pantalla» frente al «Cargando…» visible de hoy
- Categoría: 1
- Severidad: Baja
- Dónde: RF-21, RF-32
- Detección: Hoy el subtítulo de Tareas muestra «Cargando…» a la vista (status.py:921), y RF-32 obliga a conservar ese texto. RF-21 pide anunciar la carga «solo» a los lectores de pantalla. No queda claro si el «Cargando…» visible se mantiene junto al estado de carga nuevo, o si «solo» obliga a ocultarlo.
- Estado: resuelta
- Decisión: el «Cargando…» visible se mantiene; el estado de carga nuevo lo acompaña visualmente y el anuncio adicional es solo para lectores de pantalla (RF-21).

## C-39 · «Acción principal de la página» fuera de la vista Tareas
- Categoría: 1
- Severidad: Baja
- Dónde: Definiciones («Acción principal»), RF-16
- Detección: El campo de escribir y el botón Enviar solo existen en la vista Tareas (status.py:922-925). El botón de hablar se oculta según un ajuste (status.py:3263). En Apuntes, Consumo, Historial, En vivo o Ajustes no se sabe qué no debe tapar el aviso emergente, así que RF-16 no se puede verificar en esas vistas.
- Estado: resuelta
- Decisión: el aviso emergente nunca tapa el botón de hablar (cuando está visible) ni la acción principal de la vista; el plan nombra la acción principal vista por vista y el usuario la aprueba al aprobar el plan (Definiciones «Acción principal», RF-16, Casos límite).

Totales: 2 altas, 5 medias, 4 bajas (11 detecciones).
Resultado de la ronda 2: 11 resueltas (C-29 a C-39).

Duda surgida al aplicar C-35 (cambio de alcance) — abierta en la spec: las series del gráfico de Consumo (Claude y Modelo local) tienen hoy color propio, que no es acento, neutro, estado ni categoría; RF-8 no les da rol.

Duda surgida al aplicar la ronda 2 — resuelta: volumen. Aunque probablemente salgan más de 30 tareas, se mantiene una sola spec entregada por lotes, sin dividirla; la entrega puede ir por partes y la spec termina cuando cumplen todas (Contexto y objetivo, Criterios de finalización).

Duda surgida al aplicar la ronda 2 — resuelta: gráfico de Consumo. `docs/design.md` define un juego cerrado de 2-3 colores de datos, solo para gráficos, cada uno con variante clara y oscura, distinguibles entre sí también con daltonismo; los gráficos llevan leyenda en texto y esos colores no se usan fuera de gráficos (Definiciones «Colores de datos», RF-1, RF-2, RF-8, nuevos RF-49 y RF-50, Casos límite, Criterios; quitada de «Dudas abiertas»).

Duda surgida al aplicar la ronda 2 — resuelta: logo e iconos de la app instalada. Entran en el alcance («que se cambie todo»): se rediseñan según `docs/design.md` y siguen funcionando como icono de app en el iPhone y en los demás tamaños que usa hoy la página, con las mismas rutas y tamaños; si hacen falta archivos nuevos, el plan los listará para su aprobación. El selector manual de claro/oscuro sigue fuera de alcance (Objetivo, Definiciones, nueva HU-9, nuevos RF-51 y RF-52, RF-32, Casos límite, Fuera de alcance, Criterios con su checkpoint visual). Queda abierta en la spec: si la comprobación del icono en el iPhone admite reinstalar la app.

Duda surgida al aplicar la ronda 2 — resuelta: icono en el iPhone. Basta con reinstalar: la comprobación a mano se hace quitando la app de la pantalla de inicio y volviendo a añadirla; no se exige que el icono cambie solo sin reinstalar (nuevo caso límite, Criterios de finalización; quitada de «Dudas abiertas»).

## Ronda 3 (2026-11-17)

11 detecciones (2 altas, 5 medias, 4 bajas)

Ronda 3. Todas las decisiones de las rondas 1 y 2 están en la spec. Las 9 HU tienen al menos un RF y todos los RF citan una HU. Con la constitución no hay choques directos. Casi todas las detecciones salen de contrastar el nuevo alcance («toda la página», colores de datos, logo e iconos, ruta de la fuente) con lo que hace hoy `hermes/status.py`.

## C-40 · Columnas del gráfico de Consumo frente al área táctil de 44 px
- Categoría: 2
- Severidad: Alta
- Dónde: RF-25, RF-24, RF-34, RF-43, RF-32
- Detección: Cada una de las 14 columnas del gráfico es un control que se pulsa o enfoca para ver su detalle (`col.tabIndex = 0`, foco y ratón abren el tooltip; hermes/status.py:1875-1901). A 375 px caben unos 16 px por columna (margen de 44 px y separación de 6 px, status.py:441). RF-25 exige 44×44 a todo control que se pulsa en toda la página. RF-24 no permite que el gráfico se desplace por dentro: solo las filas de pestañas, subpestañas y filtros y las tablas anchas. RF-32 obliga a mantener los 14 días. Las tres cosas no se pueden cumplir a la vez, y el gráfico no figura entre las excepciones.
- Estado: resuelta
- Decisión: columnas estrechas con zona pulsable a todo el alto del gráfico (al menos 44 px), activable en toda su franja; se mantienen los 14 días sin desplazamiento; excepción justificada al ancho de 44 px, aprobada por el usuario y registrada en `docs/design.md` (RF-25, RF-43, Casos límite, Criterios).

## C-41 · El selector de color de categoría en Ajustes muestra el color tal cual
- Categoría: 2
- Severidad: Alta
- Dónde: RF-8, RF-46, Definiciones («Color de categoría»), RF-32
- Detección: Ajustes muestra cada categoría con un `input type="color"` nativo cuyo valor y muestra son el color guardado sin atenuar (hermes/status.py:3067). RF-8 y la definición dicen que la página nunca usa ese color tal cual, solo su variante atenuada como punto o borde pequeño, y nunca como fondo de un botón. RF-46 incluye «los colores de categoría» en Ajustes y RF-32 obliga a conservar esa función. Así RF-8 no se puede cumplir ni verificar en ese control.
- Estado: resuelta
- Decisión: el selector de color de categoría de Ajustes es la única excepción a RF-8: muestra el color guardado tal cual, sin elementos añadidos (sin vista previa); se registra en `docs/design.md` (Definiciones «Color de categoría», RF-8, Casos límite, Fuera de alcance, Criterios).

## C-42 · La ruta de la tipografía y el acceso remoto
- Categoría: 3
- Severidad: Media
- Dónde: RF-48, Datos personales y privacidad (4.º), Fuera de alcance (2.º)
- Detección: Por el túnel, hoy solo los iconos (`PUBLIC_FILES`) y el manifiesto se sirven sin sesión; lo demás exige sesión aprobada (hermes/status.py:3376-3392). RF-48 no dice si la ruta nueva de la fuente es pública, como los iconos, o exige sesión. Esa decisión es de seguridad, y CLAUDE.md prohíbe tocar esa parte sin spec. Tampoco se dice cómo se comprueba que la ruta solo sirve archivos de fuente y no otros archivos de la carpeta de recursos.
- Estado: resuelta
- Decisión: la ruta de la fuente exige sesión aprobada por el acceso remoto, como la página (no entra en los archivos públicos); la pantalla de acceso usa la tipografía del sistema; no se amplía lo que se sirve sin sesión; un test comprueba que la ruta solo entrega los archivos de fuente listados (RF-48, Privacidad, Casos límite, Fuera de alcance, Criterios).

## C-43 · Colores del manifiesto fijos en negro
- Categoría: 3
- Severidad: Media
- Dónde: RF-41, RF-9, Casos límite (app instalada en modo claro)
- Detección: El manifiesto de la app instalada fija `theme_color` y `background_color` en `#0a0c0f` (hermes/status.py:31-32). Esos valores son únicos y no pueden seguir el modo. RF-41 y el caso límite solo hablan del color de tema y de la barra de estado. No se dice qué pasa con estos dos valores (la pantalla de arranque y el color de tema que toma el sistema), ni si cuentan como parte del tema negro que retira RF-9.
- Estado: resuelta
- Decisión: los colores de tema y de fondo del manifiesto dejan el negro fijo y usan un neutro que funcione en los dos modos, fijado en `docs/design.md`; cuentan como parte de lo que retira RF-9 (RF-9, RF-41, Casos límite, Criterios).

## C-44 · Estados de carga nuevos en vistas que hoy no los tienen
- Categoría: 2
- Severidad: Media
- Dónde: RF-47, RF-32, RF-21
- Detección: Hoy solo muestran «Cargando…» Tareas, Ajustes e Historial (hermes/status.py:921, 1096 y 1107). Apuntes, Consumo y En vivo no tienen estado de carga. RF-47 pide un estado de carga «definido en `docs/design.md`» en todas las demás vistas, pero RF-32 solo exceptúa el estado de carga de RF-21, que es el de Tareas. No se sabe si en las vistas sin estado de carga hay que crearlo (lo que choca con RF-32) o se dejan como están, ni si llevan el anuncio para lectores de pantalla.
- Estado: resuelta
- Decisión: Apuntes, Consumo y En vivo ganan un estado de carga visual sin texto visible nuevo, con anuncio solo para lectores de pantalla; la excepción de RF-32 se amplía a los estados de carga de todas las vistas (RF-21, RF-32, RF-47, Casos límite).

## C-45 · Contraste mínimo de los colores de datos
- Categoría: 3
- Severidad: Media
- Dónde: RF-27, RF-49, RF-2, RNF-7
- Detección: RF-27 fija umbrales para texto, iconos, bordes de controles y foco, pero no para los elementos gráficos (las barras del gráfico). RF-2 pide documentar el contraste de los colores de dato, pero sin mínimo. RF-49 solo exige que se distingan entre sí con daltonismo. No hay umbral de contraste de cada color de datos frente al fondo del gráfico en claro y en oscuro, así que RNF-7 no puede medirlo.
- Estado: resuelta
- Decisión: cada color de datos tiene un contraste mínimo de 3:1 contra el fondo del gráfico, en claro y en oscuro (WCAG 1.4.11), y RNF-7 lo mide (RF-27, RNF-7, Casos límite).

## C-46 · El logo dentro de la vista En vivo
- Categoría: 3
- Severidad: Media
- Dónde: Definiciones («Logo e iconos de la app instalada», «En vivo»), RF-45, RF-51, RF-52, RF-8, RF-27
- Detección: El logo (`/logo.webp`, 1254×1254) no solo identifica la app instalada: es el centro del indicador de En vivo, sobre un disco blanco fijo y en gris al pausar (hermes/status.py:485-492 y 946). La spec no dice si a esa imagen le aplican RF-8, RF-27 y RF-5/RF-6 dentro de la vista. Tampoco dice si un único archivo, con la misma ruta (RF-52), debe verse bien sobre la paleta clara y sobre la oscura dentro de la página. Los casos límite solo cubren el icono de la pantalla de inicio.
- Estado: resuelta
- Decisión: el logo es un único archivo (misma ruta) que se ve bien sobre la paleta clara y la oscura; en En vivo, el disco detrás usa la superficie del modo activo (deja de ser blanco fijo) y en pausa el logo sigue atenuado; le aplican RF-5/RF-6 y RF-27 en la vista (Definiciones, RF-45, RF-52, Casos límite, Criterios con checkpoint del logo en En vivo en claro y oscuro).

## C-47 · ¿La leyenda y el tooltip están «dentro del gráfico»?
- Categoría: 1
- Severidad: Baja
- Dónde: RF-8, RF-50, Definiciones («Colores de datos»), Casos límite (color de datos fuera de un gráfico)
- Detección: Las muestras de color de la leyenda están fuera del contenedor del gráfico (hermes/status.py:972), y el tooltip también pinta muestras con los colores de las series (status.py:1890). RF-8 prohíbe los colores de datos «fuera de los gráficos», pero no define si la leyenda y el tooltip forman parte del gráfico. Sin ese límite, el caso límite no se puede comprobar.
- Estado: resuelta
- Decisión: la leyenda y el tooltip del gráfico cuentan como parte del gráfico y pueden usar los colores de datos (Definiciones «Colores de datos», RF-8, Casos límite).

## C-48 · «El tamaño más pequeño» del icono no coincide con el checkpoint
- Categoría: 1
- Severidad: Baja
- Dónde: RF-52, Casos límite (icono en su tamaño más pequeño), Criterios de finalización (checkpoint del logo e iconos)
- Detección: Los archivos que hay hoy son de 192, 512 y 1254 px. La pestaña del navegador usa el de 192 px reducido (hermes/status.py:235). El caso límite llama «tamaño más pequeño» a la pestaña del navegador, pero el checkpoint revisa «cada tamaño que usa hoy la página». No queda claro si el checkpoint incluye el icono a tamaño de pestaña (16-32 px).
- Estado: resuelta
- Decisión: el checkpoint del logo e iconos incluye el icono a tamaño de pestaña del navegador (16 y 32 px), además de 192, 512 y el logo (RF-52, Casos límite, Criterios).

## C-49 · «Archivos nuevos» del logo frente a «mismas rutas»
- Categoría: 2
- Severidad: Baja
- Dónde: RF-52, RF-32, Criterios de finalización («la única ruta nueva es la de la tipografía»); clarify.md (decisión del logo, ronda 2)
- Detección: La decisión de la ronda 2 dice que, si hacen falta archivos nuevos para el logo o los iconos, el plan los listará para su aprobación. La spec no lo recoge. Además, RF-52 y los criterios solo admiten las rutas de hoy más la de la fuente. No se sabe si un archivo nuevo (por ejemplo, una variante del logo para el modo oscuro) puede servirse, ni por qué ruta.
- Estado: resuelta
- Decisión: si el logo o los iconos necesitan archivos nuevos, el plan los lista para la aprobación del usuario y se sirven por el mismo mecanismo de iconos que ya existe; no hay rutas nuevas aparte de la de la fuente (RF-52, Criterios).

## C-50 · RF-48 mal ubicado y trazado
- Categoría: 5
- Severidad: Baja
- Dónde: RF-48, RF-36, sección «Accesibilidad y teclado»
- Detección: RF-48 (ruta de la fuente y cambio de la política de seguridad) y RF-36 (tipografía del sistema si la propia no carga) están en la sección de accesibilidad y teclado, y RF-48 se traza a HU-7, que pide no cambiar nada. Ninguna HU describe la necesidad que cubre la tipografía propia.
- Estado: resuelta
- Decisión: nueva HU-10 (tipografía propia y legible); RF-36 y RF-48 pasan a la nueva sección «Tipografía propia» y se trazan a HU-10 (RF-36 deja HU-3; RF-48 deja HU-3 y HU-7).

Totales: 2 altas, 5 medias, 4 bajas (11 detecciones).
Resultado de la ronda 3: 11 resueltas (C-40 a C-50).
