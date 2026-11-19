# Spec 001 — Rediseño visual de la página de Hermes
Estado: implementada (2026-11-18)

## Contexto y objetivo
La página local de Hermes creció función a función y hoy no tiene un lenguaje visual propio:
los colores, tamaños de letra, espacios y radios se decidieron caso por caso, y todas las
pestañas usan el tema negro con acento dorado que nació para «En vivo», aunque la página
también define un modo claro y otro oscuro que ese tema tapa.

El objetivo es darle a la página un lenguaje visual propio y coherente, escrito en
`docs/design.md`, y aplicarlo a fondo a **toda la página**: el marco común (cabecera,
pestañas, subpestañas, avisos, diálogos, botones y voz) y todas las vistas (Tareas con su
Calendario, Apuntes, Consumo, Historial, En vivo y Ajustes), además del logo y los iconos de
la app instalada, **sin cambiar lo que hace**:
mismas funciones, mismos datos y mismos textos visibles (con las únicas excepciones que
enumera RF-32). El tema negro y dorado se retira de toda la página y todas las vistas toman la
paleta nueva en claro y en oscuro. Es una herramienta de uso diario, así que el modo de diseño
es **Operar**: precisión, densidad útil, rapidez en el uso repetido, estados claros y poco
movimiento. Es una sola spec: la entrega puede ir por partes (por lotes), pero la spec termina
cuando cumplen todas (el marco, todas las vistas y el logo e iconos de la app instalada).

Es también la primera prueba del flujo de diseño del SDD (skill `sdd-design`): antes del plan
el usuario podrá analizar 1 o 2 sitios de referencia, de los que se toman principios, no copias.

## Usuarios
- Un único usuario, el dueño de Hermes.
- Sobre todo desde el iPhone, con la página instalada como app: 375 px de ancho, táctil, a
  menudo de pie o caminando.
- A veces desde la laptop, con teclado y ratón.
- Uso repetido varias veces al día: mirar pendientes, marcar tareas como hechas y apuntar
  cosas (tareas, gastos).

## Historias de usuario
- HU-1. Como dueño de Hermes, quiero un documento de diseño único (`docs/design.md`) para que
  esta y las siguientes specs de interfaz sigan el mismo lenguaje visual sin redecidirlo.
- HU-2. Como usuario, quiero que la página se vea en claro o en oscuro con una sola paleta
  coherente, para usarla cómoda a cualquier hora y que se sienta una sola herramienta.
- HU-3. Como usuario que la usa en el iPhone de pie o caminando, quiero leer y tocar los
  controles sin esfuerzo ni errores, para mirar pendientes y marcar hechos en segundos.
- HU-4. Como usuario, quiero que el marco común se vea y se comporte igual en toda la página,
  para no reaprender nada al cambiar de pestaña.
- HU-5. Como usuario, quiero que la vista Tareas siga el nuevo lenguaje visual y distinga de
  un vistazo lo pendiente, lo urgente y lo vencido, para decidir qué hacer sin leer todo.
- HU-6. Como usuario en la laptop, quiero usar el marco y todas las vistas con el teclado, ver
  siempre dónde está el foco y leer cómodo en una pantalla ancha, para no depender del ratón.
- HU-7. Como dueño de Hermes, quiero que el rediseño no cambie nada de lo que la página hace,
  para seguir usándola a diario sin sorpresas ni regresiones.
- HU-8. Como usuario, quiero que Apuntes (con todas sus subpestañas), Consumo, Historial, En
  vivo y Ajustes sigan el mismo lenguaje visual que Tareas, para que toda la página se sienta
  una sola herramienta y cada vista se lea y se use igual de bien.
- HU-9. Como usuario que tiene la página instalada como app, quiero que el logo y los iconos de
  la app sigan el nuevo lenguaje visual, para que la app se sienta la misma herramienta desde
  la pantalla de inicio hasta dentro de la página.
- HU-10. Como usuario, quiero una tipografía propia y legible, para leer cómodo y reconocer
  Hermes.

## Definiciones
- **Marco**: las piezas comunes a todas las vistas: cabecera (marca, pestañas e indicador de
  conexión), pestañas de sección, subpestañas, avisos (el aviso emergente con «Deshacer» y el
  aviso de «Hermes no responde»), diálogos (editor de tarea, confirmación y foto de recibo),
  botones (principal, secundario y de icono), los iconos de la interfaz, el botón de hablar y
  el panel de voz. También cuentan como marco las reglas de estilo que comparten varias vistas
  (por ejemplo, el fondo y el texto de la página, el estado vacío, el aviso de deshacer, el
  botón principal y el botón de icono).
- **Vistas**: las seis pestañas de sección de la página:
  - **Tareas**: título y última actualización, campo para escribir una tarea u orden,
    contadores por estado (que filtran), selector Lista/Calendario, la vista Calendario,
    filtros por categoría, grupos de tareas con sus tarjetas, y sus estados de carga, vacío y
    error.
  - **Apuntes**: título, explicación, subpestañas (Listas, Hábitos, Notas, Fechas,
    Seguimientos, Gastos, Pagos y Lecturas), el aviso de silencio y, en cada subpestaña, sus
    formularios, listas, tarjetas, calendario, resúmenes y estados.
  - **Consumo**: título, explicación, cifras del día y del mes, el gráfico de los últimos 14
    días con su leyenda y su vista como tabla, y las tablas por uso y de últimas llamadas.
  - **Historial**: título, explicación, buscador, conversación y lista de las últimas veces
    que escuchó por voz.
  - **En vivo**: el indicador animado de estado, el mensaje de estado y su pista, el botón
    del micrófono y el medidor de nivel.
  - **Ajustes**: título, explicación, aviso de reinicio, dispositivos con la página abierta,
    los grupos de ajustes con todos sus controles (incluidos Funciones y los colores de
    categoría) y la barra de Guardar.
- **Acento**: el único color de marca; señala solo la acción principal, la selección y el
  foco.
- **Colores de estado**: juego cerrado de colores que comunican un estado y no la marca:
  éxito (incluido «conectado»), aviso y peligro (incluidos urgente, vencida y
  «desconectado»).
- **Colores de datos**: juego cerrado de 2 o 3 colores, solo para gráficos (hoy, el de
  Consumo), cada uno con su variante para claro y para oscuro, distinguibles entre sí también
  para personas con daltonismo. No son acento, neutro, estado ni categoría, y no se usan fuera
  de los gráficos. La leyenda y el tooltip de un gráfico cuentan como parte del gráfico.
- **Logo e iconos de la app instalada**: el logo de Hermes y los iconos que la página declara
  hoy para la app instalada y la pestaña del navegador (el de la pantalla de inicio del iPhone
  y los demás tamaños que usa hoy). El logo es un único archivo, que se usa también en el
  centro del indicador de En vivo. No incluye los iconos de la interfaz, que son marco.
- **Urgencia**: cada tarea tiene una de tres: Urgente (urgencia «alta»), Normal y Baja.
- **Color de categoría**: el color que el usuario elige para cada categoría de tarea en
  Ajustes (las categorías y sus colores los configura él; se guardan como hoy). La página no
  lo usa tal cual: a partir de él genera al pintar una **variante atenuada** para claro y otra
  para oscuro, y solo la usa como punto o borde pequeño junto a la categoría. Única excepción:
  el selector de color de cada categoría en Ajustes muestra el color guardado tal cual, porque
  es lo que el usuario elige.
- **Neutros con tinte**: fondos, superficies, líneas y textos secundarios que no son grises
  puros, sino que llevan un matiz leve y común.
- **Tokens**: los valores con nombre que fija `docs/design.md` (colores, tamaños de letra,
  espacios, radios y transiciones). Un token pertenece a una **escala**: un conjunto cerrado de
  valores permitidos.
- **Texto de cuerpo**: el título de las tareas, los párrafos, el texto de los avisos, los
  mensajes del historial y el de todos los campos de entrada. No son cuerpo los metadatos,
  chips, etiquetas y rótulos de contadores.
- **Texto grande**: según WCAG, el de al menos 24 px, o de al menos 18,66 px en negrita.
- **Acción principal**: en la vista Tareas, la caja de escribir/hablar (campo, botón de enviar
  y botón de hablar); en cada una de las demás vistas, la que nombre el plan para esa vista y
  apruebe el usuario al aprobar el plan; en el editor de tarea, su botón Guardar; en el
  diálogo de confirmación, su botón de confirmar; en el diálogo de foto de recibo, su botón de
  cerrar.
- **Tarea urgente**: la que tiene urgencia «alta».
- **Tarea vencida**: la no terminada cuya fecha límite (o, si no tiene, su fecha de aviso) ya
  pasó.
- **Tarea pendiente**: la que no está terminada.
- **Textos visibles**: todo texto que se ve en la página, tanto el escrito en ella como el que
  genera su script al pintar (por ejemplo, los textos de los estados vacíos o «Vencida · …»).
- **Anti-patrón**: una señal de interfaz genérica o un error frecuente de los que enumera
  `docs/design.md`. Esa lista es la que manda: parte de la de la skill de diseño y puede
  ampliarla.
- **Excepción justificada**: un uso fuera de una escala o un anti-patrón que está escrito en
  `docs/design.md` con su motivo y que el usuario aprobó.
- **Importe**: una cantidad de dinero mostrada en pantalla.

## Requisitos funcionales

### Documento de diseño
- RF-1 (HU-1): EL SISTEMA contará con un documento `docs/design.md` que fije, como mínimo: el
  modo de la superficie (Operar), la paleta en claro y en oscuro, la escala tipográfica, la
  escala de espaciado, la escala de radios y la forma (bordes, sombras), el movimiento, los
  componentes del marco y de cada vista con sus estados, los colores de datos, el logo y los
  iconos de la app instalada, y los anti-patrones del proyecto.
- RF-2 (HU-1): EL SISTEMA documentará en `docs/design.md`, para cada color de la paleta, su
  rol (fondo, superficie, texto, línea, acento, estado o dato) y el contraste medido frente a cada
  fondo sobre el que se usa (página, tarjeta y superficie suave, según corresponda), en claro
  y en oscuro; para los colores de categoría documentará la regla con la que se genera su
  variante atenuada en claro y en oscuro.
- RF-3 (HU-1): EL SISTEMA documentará en `docs/design.md` qué principios se tomaron de cada
  sitio de referencia analizado y por qué, sin copiar su identidad (colores, logotipos,
  tipografías de marca ni maquetación literal); si no se analizó ninguno, lo indicará con
  «sin referencias».
- RF-4 (HU-1): EL SISTEMA registrará en `docs/design.md` cada excepción a una escala o a un
  anti-patrón que use la página, con su motivo y la constancia de que el usuario la aprobó;
  las que surjan al implementar se aprueban una a una, sin reaprobar el documento entero.

### Paleta y modos
- RF-5 (HU-2): MIENTRAS el sistema operativo del dispositivo esté en modo claro, EL SISTEMA
  mostrará todas las vistas con la variante clara de la paleta.
- RF-6 (HU-2): MIENTRAS el sistema operativo del dispositivo esté en modo oscuro, EL SISTEMA
  mostrará todas las vistas con la variante oscura de la paleta.
- RF-7 (HU-2): CUANDO el sistema operativo cambie entre claro y oscuro con la página abierta,
  EL SISTEMA aplicará la variante correspondiente sin recargar la página, sin cerrar los
  diálogos abiertos y sin perder lo escrito.
- RF-8 (HU-2): EL SISTEMA usará en toda la página solo: un único color de acento (con su
  variante para claro y para oscuro), neutros con tinte, los colores de estado y, solo dentro
  de los gráficos, los colores de datos, todos enumerados en `docs/design.md`, más las
  variantes atenuadas de los colores de categoría. Los colores de datos no se usarán fuera de
  los gráficos; la leyenda y el tooltip de un gráfico cuentan como parte de él y pueden
  usarlos.
  La urgencia Urgente usará el color de estado peligro; Normal y Baja usarán neutros (Baja más
  tenue que Normal) y se distinguirán también por su texto. El color de categoría se usará
  solo como punto o borde pequeño (también dentro de un filtro o del selector de categoría) y
  nunca como fondo, borde o texto de un botón ni en el foco; el texto de la categoría irá en
  un color neutro. La única excepción es el selector de color de cada categoría en Ajustes,
  que mostrará el color guardado tal cual, sin elementos añadidos (sin vista previa); esta
  excepción quedará registrada en `docs/design.md`.
- RF-9 (HU-2): EL SISTEMA no aplicará el tema negro y dorado de «En vivo» en ninguna vista,
  tampoco en la vista En vivo, y `docs/design.md` dejará escrita esa retirada. Los colores de
  tema y de fondo fijos en negro del manifiesto de la app instalada cuentan como parte de ese
  tema y también se retiran (RF-41).

### Tipografía, espaciado y forma
- RF-10 (HU-3): EL SISTEMA mostrará el texto de cuerpo de toda la página a 16 px; los
  metadatos, chips, etiquetas y rótulos de contadores podrán ir a 13 o 14 px.
- RF-11 (HU-1, HU-3): EL SISTEMA usará en toda la página solo tamaños de letra de la escala
  tipográfica de `docs/design.md`, que tendrá como máximo 5 tamaños (por ejemplo, 13, 14, 16,
  20 y 24 px).
- RF-12 (HU-5, HU-8): EL SISTEMA mostrará con cifras tabulares (todas del mismo ancho): los
  cinco contadores por estado de Tareas (Pendientes, Urgentes, Vencidas, Para hoy y
  Terminadas), los números de día de cualquier calendario de la página (Calendario de Tareas
  y Fechas de Apuntes), las cifras y tablas de Consumo y cualquier importe de la página.
- RF-13 (HU-1, HU-4): EL SISTEMA usará en toda la página solo márgenes, rellenos y
  separaciones de la escala de espaciado, y solo radios de la escala de radios, de
  `docs/design.md`.

### Marco
- RF-14 (HU-4): EL SISTEMA mostrará la cabecera, la marca, las pestañas y el indicador de
  conexión con los tokens de `docs/design.md`, con la pestaña activa distinguible de las demás
  por algo más que el color; el indicador de conexión usará los colores de estado, no el
  acento.
- RF-15 (HU-4): EL SISTEMA mostrará las subpestañas con los tokens de `docs/design.md`, con la
  activa distinguible de las demás por algo más que el color.
- RF-16 (HU-4): EL SISTEMA mostrará los avisos (el aviso emergente, con o sin «Deshacer», y el
  aviso de «Hermes no responde») con los tokens de `docs/design.md`; en cualquier vista, el
  aviso nunca tapará el botón de hablar (cuando esté visible) ni la acción principal de la
  vista, ni la de un diálogo abierto (Guardar, confirmar o cerrar, según el diálogo), tampoco
  con el teclado virtual abierto.
- RF-17 (HU-4): EL SISTEMA mostrará los diálogos (editor de tarea, confirmación y foto de
  recibo) con los tokens de `docs/design.md`; a 375×812 px, la acción principal de cada
  diálogo (Guardar en el editor de tarea, confirmar en el de confirmación y cerrar en el de
  foto de recibo) se verá sin desplazar con el teclado virtual cerrado y será alcanzable con
  él abierto.
- RF-18 (HU-4): EL SISTEMA mostrará los botones en tres variantes (principal, secundario y de
  icono) definidas en `docs/design.md`, cada una con estados de reposo, encima (en dispositivos
  con puntero), pulsado, foco, desactivado y, si aplica, en curso.
- RF-38 (HU-4): EL SISTEMA mostrará el botón de hablar y el panel de voz con los tokens de
  `docs/design.md`, con sus estados distinguibles por algo más que el color.

### Vista Tareas
- RF-19 (HU-5): EL SISTEMA mostrará la vista Tareas (campo de entrada, contadores por estado,
  selector Lista/Calendario, vista Calendario, filtros por categoría, grupos y tarjetas de
  tarea) con los tokens de `docs/design.md`.
- RF-20 (HU-5): EL SISTEMA distinguirá en la vista Tareas las tareas urgentes y las vencidas
  de las demás por color de estado más un icono o un peso de letra, usando solo los textos que
  ya existen (como «Urgente» o «Vencida · …»), sin añadir textos visibles nuevos.
- RF-35 (HU-5): EL SISTEMA distinguirá en la vista Tareas las tareas pendientes de las
  terminadas por algo más que el color.
- RF-21 (HU-5): MIENTRAS la vista Tareas esté cargando, EL SISTEMA mantendrá visible el
  «Cargando…» de hoy, lo acompañará de un estado de carga visual definido en `docs/design.md`
  sin texto visible nuevo, y añadirá un anuncio de carga solo para lectores de pantalla (la
  misma excepción de RF-32 cubre los estados de carga de RF-47).
- RF-22 (HU-5): CUANDO no haya tareas que mostrar con el filtro activo, EL SISTEMA mostrará el
  estado vacío definido en `docs/design.md`, con el mismo texto que hoy.
- RF-23 (HU-5): SI Hermes no responde, ENTONCES EL SISTEMA mostrará el aviso de error definido
  en `docs/design.md`, con el mismo texto que hoy, sin tapar la vista ni la acción principal.

### Demás vistas
- RF-34 (HU-2, HU-8): EL SISTEMA mostrará las vistas Apuntes, Consumo, Historial, En vivo y
  Ajustes rediseñadas según `docs/design.md`, con los mismos requisitos que el marco y la vista
  Tareas en paleta y modos, tipografía, espaciado y forma, uso táctil y pantalla ancha,
  accesibilidad y teclado, movimiento y tokens (RF-5 a RF-18, RF-24 a RF-31, RF-36 a RF-41),
  medidos igual a 375 y a 1280 px, en claro y en oscuro.
- RF-42 (HU-8): EL SISTEMA mostrará la vista Apuntes (subpestañas, aviso de silencio y, en cada
  subpestaña, sus formularios, listas, tarjetas, calendario de Fechas y resúmenes de Gastos y
  Pagos) con los tokens de `docs/design.md`.
- RF-43 (HU-8): EL SISTEMA mostrará la vista Consumo (cifras, gráfico con su leyenda, su vista
  como tabla y las tablas por uso y de últimas llamadas) con los tokens de `docs/design.md`,
  con las series del gráfico distinguibles por algo más que el color. El gráfico mantendrá los
  14 días sin desplazamiento interno; cada columna será estrecha, pero su zona pulsable ocupará
  todo el alto del gráfico (al menos 44 px) y se activará tocando su franja entera (excepción
  al ancho de RF-25).
- RF-44 (HU-8): EL SISTEMA mostrará la vista Historial (buscador, conversación y lista de
  escuchas por voz) con los tokens de `docs/design.md`.
- RF-45 (HU-8): EL SISTEMA mostrará la vista En vivo (indicador de estado, mensaje y pista,
  botón del micrófono y medidor de nivel) con los tokens de `docs/design.md`, con sus estados
  (por ejemplo, escuchando o en pausa) distinguibles por algo más que el color. El disco
  detrás del logo usará la superficie del modo activo (deja de ser blanco fijo) y, en pausa, el
  logo se verá atenuado, como hoy; al logo dentro de la vista le aplican RF-5, RF-6 y RF-27.
- RF-46 (HU-8): EL SISTEMA mostrará la vista Ajustes (aviso de reinicio, dispositivos con la
  página abierta, grupos de ajustes con todos sus controles y barra de Guardar) con los tokens
  de `docs/design.md`.
- RF-47 (HU-8): MIENTRAS una de las demás vistas (o una subpestaña de Apuntes) esté cargando,
  vacía o sin respuesta de Hermes, EL SISTEMA mostrará los estados de carga, vacío y error
  definidos en `docs/design.md`, con los mismos textos visibles que hoy. Apuntes, Consumo y En
  vivo, que hoy no tienen estado de carga, ganarán uno visual sin texto visible nuevo y con su
  anuncio solo para lectores de pantalla (excepción de RF-32).

### Uso táctil, móvil y pantalla ancha
- RF-24 (HU-3): MIENTRAS la página se muestre a 375 px o a 1280 px de ancho, EL SISTEMA no
  desplazará la página en horizontal ni recortará controles, en ninguna vista; las filas de
  pestañas, subpestañas y filtros, y las tablas anchas, podrán desplazarse por dentro, y los
  títulos largos podrán cortarse con puntos suspensivos tras una o dos líneas, mostrándose
  completos al abrir el elemento.
- RF-40 (HU-3, HU-5, HU-8): CUANDO una vista no tenga elementos, tenga una lista más alta que
  la pantalla o el texto se amplíe al 200 %, EL SISTEMA la mostrará sin solapes y sin
  desplazamiento horizontal de la página.
- RF-25 (HU-3): MIENTRAS el puntero principal sea táctil o la página se muestre a 375 px de
  ancho, EL SISTEMA dará a cada control que se pulsa en toda la página un área de al menos
  44×44 px; con ratón en la laptop el área podrá ser menor, con un mínimo de 32 px de alto.
  Los enlaces dentro de un texto quedan exentos. Las columnas del gráfico de Consumo quedan
  exentas del ancho de 44 px (no del alto): su zona pulsable ocupa todo el alto del gráfico,
  al menos 44 px, y toda su franja (RF-43); es una excepción justificada, aprobada por el
  usuario y registrada en `docs/design.md`.
- RF-26 (HU-3): MIENTRAS la página se use como app instalada en el iPhone, EL SISTEMA
  respetará las zonas seguras de la pantalla (muesca, barra de inicio) en la cabecera, los
  avisos, los diálogos, el botón de hablar, el panel de voz y el margen inferior del
  contenido.
- RF-37 (HU-6): MIENTRAS la página se muestre a 1280 px de ancho o más, EL SISTEMA limitará el
  contenido de cada vista a un ancho máximo legible fijado en `docs/design.md`, sin estirarlo
  a toda la pantalla.

### Accesibilidad y teclado
- RF-27 (HU-2, HU-3): EL SISTEMA mantendrá en toda la página, en claro y en oscuro y sobre
  cada fondo donde se use cada color, un contraste de al menos 4,5:1 en texto normal y 3:1 en
  texto grande, iconos, bordes de controles e indicador de foco. Los controles desactivados
  quedan exentos, pero se verán claramente como no disponibles. El punto o borde de categoría
  es decorativo (el texto de la categoría lo acompaña siempre) y su variante atenuada se
  genera con la regla de RF-2. Cada color de datos (las barras de un gráfico) tendrá un
  contraste de al menos 3:1 contra el fondo del gráfico, en claro y en oscuro (WCAG 1.4.11).
- RF-28 (HU-6): CUANDO un control de cualquier vista o del marco reciba el foco con el
  teclado, EL SISTEMA mostrará un indicador de foco visible con contraste de al menos 3:1, y
  el orden de tabulación seguirá el orden visual.
- RF-29 (HU-6): CUANDO se abra cualquier diálogo, EL SISTEMA llevará el foco a su interior y lo
  mantendrá dentro mientras esté abierto, lo cerrará con Escape y, al cerrarlo, devolverá el
  foco al control que lo abrió.
- RF-30 (HU-3): SI el dispositivo pide reducir el movimiento, ENTONCES EL SISTEMA no animará
  desplazamientos ni cambios de escala en ninguna parte de la página (incluidos el panel de
  voz y el indicador de En vivo).
- RF-31 (HU-1, HU-3): EL SISTEMA usará en toda la página solo las transiciones y animaciones
  que fije `docs/design.md` para el modo Operar, con su duración máxima.

### Tipografía propia
- RF-36 (HU-10): SI la tipografía propia no se carga, ENTONCES EL SISTEMA mostrará la página
  con la tipografía del sistema sin solapes y sin desplazamiento horizontal de la página.
- RF-48 (HU-10): EL SISTEMA servirá la tipografía propia desde los recursos de la propia app
  por una ruta nueva dedicada solo a los archivos de fuente listados, y su política de
  seguridad de contenido permitirá fuentes solo del propio origen. Por el acceso remoto, esa
  ruta exigirá sesión aprobada, como la página: no se añade a lo que se sirve sin sesión, y la
  pantalla de acceso usa la tipografía del sistema. Es la única excepción a «no tocar la
  seguridad» y a «mismas rutas»: el token, el Host, el Origin, las sesiones y el resto de la
  política no cambian. Un test comprobará que la ruta solo entrega los archivos de fuente
  listados y ningún otro archivo de la carpeta de recursos.

### Tokens
- RF-39 (HU-1, HU-4): EL SISTEMA definirá en `docs/design.md` cada color, tamaño de letra,
  espacio, radio y transición como un token con nombre, y todo el estilo de la página usará
  solo esos tokens (las variantes de categoría, a partir de la regla de RF-2).

### Sin cambios de comportamiento
- RF-32 (HU-7): EL SISTEMA conservará las mismas funciones, rutas, datos guardados y textos
  visibles de la página. Como únicas excepciones, se permiten: textos solo para lectores de
  pantalla (etiquetas accesibles y similares), los estados de carga visuales sin texto visible
  nuevo de RF-21 y RF-47 (Tareas, Apuntes, Consumo y En vivo), el manejo de foco
  y Escape de RF-29, la ruta de la tipografía y el cambio de política de RF-48, y la imagen
  del logo y de los iconos de la app instalada (RF-51, RF-52), que cambia sin cambiar sus
  rutas ni sus tamaños.
- RF-33 (HU-7): EL SISTEMA conservará los identificadores, clases y atributos de los que
  dependen los scripts de la página o, si alguno cambia de nombre, lo cambiará también en
  todos sus usos en el mismo cambio y lo registrará en una tabla «antes → después».
- RF-41 (HU-2): EL SISTEMA hará que el color de tema de la app instalada siga el modo claro u
  oscuro activo y cambie al momento si el modo cambia con la app abierta; la barra de estado
  del iPhone acertará con el modo al abrir la app (iOS no siempre la repinta con la app
  abierta). Los colores de tema y de fondo del manifiesto de la app, que son únicos, dejarán el
  negro fijo y usarán un neutro que funcione en los dos modos, fijado en `docs/design.md`.

### Colores de datos
- RF-49 (HU-1, HU-8): EL SISTEMA definirá en `docs/design.md` un juego cerrado de 2 o 3 colores
  de datos, cada uno con su variante para claro y para oscuro, y documentará que se
  distinguen entre sí también con daltonismo (al menos protanopía, deuteranopía y
  tritanopía) y cómo se comprobó.
- RF-50 (HU-8): EL SISTEMA pintará cada serie de un gráfico (hoy, Claude y Modelo local en
  Consumo) con un color de datos distinto, en la variante del modo activo, y el gráfico
  llevará una leyenda con el nombre de cada serie en texto.

### Logo e iconos de la app instalada
- RF-51 (HU-9): EL SISTEMA mostrará un logo y unos iconos de la app instalada rediseñados según
  `docs/design.md` (paleta, forma y principios), coherentes con la marca de la cabecera.
- RF-52 (HU-9): EL SISTEMA ofrecerá el logo y los iconos de la app instalada en los mismos
  tamaños y por las mismas rutas que hoy, y cada uno se verá completo y reconocible en su
  tamaño, incluido el más pequeño (el de pestaña del navegador, a 16 y 32 px) y el icono de la
  pantalla de inicio del iPhone. El logo seguirá siendo un único archivo, con la misma ruta,
  que se verá bien sobre la paleta clara y sobre la oscura. Si el logo o los iconos necesitan
  archivos nuevos, el plan los listará para la aprobación del usuario y se servirán por el
  mismo mecanismo de iconos que ya existe; no habrá más rutas nuevas que la de la tipografía
  (RF-48).

## Requisitos no funcionales
- RNF-1: La página no carga JS, CSS ni fuentes externas en tiempo de ejecución: todo va en la
  propia página o en sus recursos locales, como exige su política de seguridad de contenido.
- RNF-2: La página usa una tipografía propia, servida en local desde los recursos de Hermes
  (RF-48). Antes de descargarla se pide permiso al usuario con su nombre, origen, licencia y
  tamaño.
- RNF-3: Las pruebas automáticas del proyecto siguen en verde.
- RNF-4: La interfaz se verifica en local a 375×812 y 1280×800, en claro y en oscuro, en todas
  las vistas, revisando la consola y las peticiones fallidas.
- RNF-5: Interfaz y textos en español (constitución).
- RNF-6: Un test automático comprueba que todo el estilo de la página solo usa los tokens de
  `docs/design.md` (RF-39).
- RNF-7: Una comprobación en el navegador mide en todas las vistas el contraste (RF-27,
  incluido el de cada color de datos contra el fondo del gráfico), el
  área de 44 px (RF-25) y la ausencia de desplazamiento horizontal de la página (RF-24), a 375
  y 1280 px, en claro y en oscuro.
- RNF-8: Un test automático compara los textos visibles (incluidos los que genera el script) y
  los identificadores y clases que usa el script de la página contra una lista de referencia
  tomada antes del cambio; los cambios de nombre registrados en la tabla «antes → después» de
  RF-33 se aceptan, y el test comprueba además que el nombre viejo ya no aparece en ningún uso
  (RF-32, RF-33).

## Datos personales y privacidad
- La página muestra tareas, recordatorios, gastos, pagos, notas, conversaciones y otros datos
  personales del usuario; esta spec no cambia qué datos se muestran, guardan ni envían.
- Las capturas del checkpoint visual, de las pruebas y de `docs/design.md` usan solo datos
  ficticios, y las capturas no se versionan.
- Los análisis de sitios de referencia no incluyen datos del usuario.
- La ruta nueva de la tipografía solo sirve los archivos de fuente listados de la app (lo
  comprueba un test); no expone datos ni otros archivos de la carpeta de recursos.
- Por el acceso remoto, la ruta de la tipografía exige sesión aprobada, como la página; lo que
  se sirve sin sesión no se amplía, y la pantalla de acceso usa la tipografía del sistema.

## Aislamiento entre usuarios o tenants
No aplica: Hermes tiene un único usuario.

## Casos límite
- Título de tarea muy largo o con una palabra sin espacios (por ejemplo, un enlace) a 375 px:
  se corta con puntos suspensivos tras una o dos líneas sin desbordar la tarjeta y se ve
  completo al abrir la tarea. Lo mismo para nombres largos en Apuntes y enlaces largos en
  Lecturas o en el Historial.
- Muchas categorías en los filtros a 375 px: la fila se desplaza por dentro; la página no se
  desplaza en horizontal.
- Seis pestañas de sección u ocho subpestañas de Apuntes a 375 px: todas alcanzables
  desplazando su fila, sin desplazar la página entera.
- Contadores con tres o más dígitos, y cifras grandes en Consumo: no rompen la fila y sus
  cifras quedan alineadas.
- Tablas anchas de Consumo a 375 px: se desplazan por dentro; la página no.
- Cambio de modo claro/oscuro del sistema con un diálogo abierto o con texto a medio escribir:
  cambia la paleta, el diálogo sigue abierto y el texto se conserva.
- App instalada en modo claro: el color de tema y la barra de estado son claros al abrirla
  (hoy están fijados en negro). Si el modo cambia con la app abierta, el color de tema cambia
  al momento; la barra de estado puede no repintarse hasta volver a abrir la app. La pantalla
  de arranque y el color que toma el sistema del manifiesto usan el neutro de dos modos fijado
  en `docs/design.md`, no el negro.
- Aviso emergente mientras el botón de hablar o la acción principal de la vista están
  visibles, o con el teclado virtual abierto: el aviso no los tapa, en ninguna vista.
- Botón de hablar oculto por su ajuste: el aviso solo debe no tapar la acción principal de la
  vista.
- Editor de tarea a 375×812: Guardar visible sin desplazar con el teclado cerrado y alcanzable
  con el teclado abierto.
- Texto ampliado al 200 %: sin solapes, sin desplazamiento horizontal de la página y sin
  pérdida de contenido ni de funciones, en todas las vistas.
- Color de categoría elegido por el usuario muy claro, muy oscuro o casi igual al acento o a
  un color de estado: el texto de la categoría sigue legible (va en neutro), el punto o borde
  usa la variante atenuada y no se confunde con un botón ni con el foco.
- Categoría nueva creada en Ajustes: su color se pinta con la misma regla, sin cambiar cómo se
  guarda.
- Selector de color de una categoría en Ajustes: muestra el color guardado tal cual, sin
  atenuar y sin vista previa añadida; es la única excepción a RF-8.
- Urgencias Normal y Baja: se distinguen entre sí y de Urgente por su texto, además del tono.
- Colores de estado en claro y en oscuro: cumplen el contraste sobre cada fondo y no se
  confunden con el acento.
- Lista vacía en cualquier vista o subpestaña: se ve el estado vacío con su texto actual.
  Lista con muchos elementos: sin solapes ni desplazamiento horizontal. Calendarios (Tareas y
  Fechas): siguen los tokens y no desplazan la página en horizontal.
- Página sin conexión con Hermes: el aviso se ve sin tapar la vista ni su acción principal.
- Vista En vivo, que hoy depende del tema negro y dorado y anima su indicador: toma la paleta
  nueva, sigue legible en claro y en oscuro, y su animación sigue RF-30 y RF-31 (si se
  conserva fuera de lo que fija `docs/design.md`, como excepción justificada).
- Logo dentro de En vivo, en claro y en oscuro: el disco detrás usa la superficie del modo
  activo (no blanco fijo) y el logo se reconoce en ambos; en pausa se ve atenuado, como hoy.
- Apuntes, Consumo o En vivo cargando: muestran su estado de carga visual, sin texto visible
  nuevo, y lo anuncian solo a lectores de pantalla.
- La tipografía propia no carga (por ejemplo, la ruta de la fuente falla): se usa la del
  sistema sin romper el diseño, y la consola no muestra errores de la política de seguridad.
- Acceso remoto sin sesión aprobada: la ruta de la fuente no entrega nada y la pantalla de
  acceso se ve con la tipografía del sistema.
- Petición a la ruta de la fuente con el nombre de otro archivo de la carpeta de recursos (o
  con una ruta relativa que intente salir de ella): no se entrega.
- Pantalla de 1280 px o más: el contenido de ninguna vista se estira más allá del ancho máximo
  legible.
- Botones desactivados: se ven claramente como no disponibles aunque no lleguen al contraste
  mínimo.
- Gráfico de Consumo con una sola serie con datos, o sin datos: la leyenda sigue nombrando las
  series en texto y el gráfico sigue usando solo colores de datos; su vista como tabla se
  mantiene.
- Gráfico de Consumo visto con daltonismo o en escala de grises: las series se distinguen por
  su color de datos y por algo más que el color (RF-43), y la leyenda las nombra.
- Un color de datos en cualquier lugar fuera de un gráfico (un botón, un texto, un fondo): no
  está permitido (RF-8). Las muestras de color de la leyenda y del tooltip del gráfico sí,
  porque cuentan como parte del gráfico.
- Gráfico de Consumo a 375 px: los 14 días caben sin desplazamiento; cada columna, aunque
  estrecha, se activa tocando cualquier punto de su franja a todo el alto del gráfico (al
  menos 44 px).
- Colores de datos en claro y en oscuro: cada uno llega a 3:1 contra el fondo del gráfico.
- Icono de la app en su tamaño más pequeño (pestaña del navegador, 16 y 32 px): se reconoce y
  no pierde detalles esenciales. Icono de la pantalla de inicio del iPhone: se ve completo, sin recortes
  por las esquinas redondeadas que aplica iOS.
- Pantalla de inicio del iPhone en modo claro o en modo oscuro: el icono se reconoce en ambos.
- App ya instalada en el iPhone que sigue mostrando el icono anterior: iOS lo guarda y no
  siempre lo cambia sola. No se exige que cambie sin reinstalar; para ver el icono nuevo se
  quita la app de la pantalla de inicio y se vuelve a añadir.

## Fuera de alcance
- Cambiar funciones, rutas o datos guardados de la página, y añadir textos visibles nuevos
  (salvo las excepciones de RF-32).
- La seguridad de la página (token, Host, Origin y el resto de la política de contenido) y el
  acceso remoto, salvo el cambio mínimo de RF-48 para servir la tipografía propia; no se amplía
  lo que se sirve sin sesión.
- Una vista previa u otros elementos añadidos al selector de color de categoría de Ajustes.
- Cambiar cómo se eligen o se guardan las categorías y sus colores.
- Telegram.
- Un selector manual de claro/oscuro en la página (posible spec posterior).

## Criterios de finalización
- Es una sola spec: la entrega puede ir por partes (por lotes), pero la spec solo termina
  cuando se cumplen todos estos criterios.
- Existe `docs/design.md` con lo que piden RF-1 a RF-4, RF-39 y RF-49, y el usuario lo aprobó.
- Toda excepción a una escala o a un anti-patrón en la página está escrita en
  `docs/design.md` con su motivo y aprobada por el usuario; el reviewer no encuentra ninguna
  sin justificar. Entre ellas están el ancho de las columnas del gráfico de Consumo (RF-25,
  RF-43) y el selector de color de categoría de Ajustes (RF-8).
- El marco y todas las vistas (Tareas con Calendario, Apuntes, Consumo, Historial, En vivo y
  Ajustes) siguen `docs/design.md` (RF-5 a RF-31 y RF-34 a RF-50), y el gráfico de Consumo usa
  solo colores de datos con su leyenda en texto (RF-50).
- El logo y los iconos de la app instalada están rediseñados (RF-51, RF-52) y su checkpoint
  visual está aprobado por el usuario: cada tamaño que usa hoy la página (192 y 512 px y el
  logo) más el icono a tamaño de pestaña del navegador (16 y 32 px), sobre fondo claro y
  oscuro; una vista del icono con las esquinas redondeadas de iOS; y el logo dentro de En vivo,
  en claro y en oscuro (y en pausa).
- Si el logo o los iconos necesitaron archivos nuevos, el usuario los aprobó al aprobar el
  plan y se sirven por el mecanismo de iconos que ya existe, sin rutas nuevas (RF-52).
- El test de tokens (RNF-6), la comprobación en el navegador de contraste, área táctil y
  desplazamiento en todas las vistas (RNF-7) y el test de textos e identificadores con su
  tabla «antes → después» (RNF-8) pasan.
- El checkpoint visual de cada pantalla o vista nueva (375 y 1280 px, claro y oscuro, con
  datos ficticios) está aprobado por el usuario.
- La política de seguridad solo cambió para permitir fuentes del propio origen, y la única ruta
  nueva es la de la tipografía (RF-48), que exige sesión aprobada por el acceso remoto; lo que
  se sirve sin sesión no cambió, y el test de RF-48 (solo entrega los archivos de fuente
  listados) pasa.
- Los colores del manifiesto ya no son negro fijo: usan el neutro de dos modos de
  `docs/design.md` (RF-9, RF-41).
- El usuario comprobó a mano en su iPhone, con la app instalada: las zonas seguras (RF-26),
  que la barra de estado acierta con el modo al abrir la app y que el color de tema sigue el
  modo activo (RF-41), y que el icono nuevo de la pantalla de inicio se ve completo y
  reconocible (RF-52). Para el icono, la comprobación se hace tras quitar la app de la
  pantalla de inicio y volver a añadirla; no se exige que cambie sin reinstalar.
- Las funciones, rutas, datos y textos no cambiaron salvo las excepciones de RF-32 (RF-32 y
  RF-33).
- Las pruebas automáticas pasan.

## Dudas abiertas
Ninguna.
