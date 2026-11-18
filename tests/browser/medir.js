// Medición de la página de Hermes en el navegador (spec 001, RNF-7; plan 3.6).
// Se pega entero como «function» de browser_evaluate (MCP de Playwright) con la vista ya abierta.
// Devuelve cuatro listas; vacías = verde:
//   desborde  : la página se desplaza en horizontal (RF-24) y qué elementos se salen
//   pequenos  : controles por debajo de 44×44 (táctil o ≤ 640 px) o de 32 de alto (ratón) (RF-25)
//   contraste : texto < 4,5:1 (3:1 si es grande); bordes de control, iconos y barras .seg < 3:1 (RF-27)
//   escala    : tamaños de letra fuera de {13, 14, 16, 20, 24} px (RF-11)
// Y «contexto» (vista, ancho, modo) para saber de qué medición se trata.
() => {
  const ESCALA = [13, 14, 16, 20, 24];
  const W = window.innerWidth;
  const tactil = matchMedia("(pointer: coarse)").matches || W <= 640;

  // --- Colores: cualquier valor CSS se normaliza pintándolo en un canvas de 1×1 ---
  const ctx = Object.assign(document.createElement("canvas"), { width: 1, height: 1 }).getContext("2d", { willReadFrequently: true });
  const cache = new Map();
  function rgba(css) {
    if (cache.has(css)) return cache.get(css);
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "#000"; ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    const out = { r, g, b, a: a / 255 };
    cache.set(css, out);
    return out;
  }
  const sobre = (top, base) => ({  // Pinta «top» (con su alfa) encima de «base» (opaco).
    r: top.r * top.a + base.r * (1 - top.a), g: top.g * top.a + base.g * (1 - top.a),
    b: top.b * top.a + base.b * (1 - top.a), a: 1,
  });
  const lum = c => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const razon = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const hex = c => "#" + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, "0")).join("");

  // Fondo real detrás de un elemento: sus fondos y los de sus ancestros, compuestos hasta uno opaco.
  function lienzo() {
    const html = rgba(getComputedStyle(document.documentElement).backgroundColor);
    return html.a === 1 ? html : sobre(html, rgba("Canvas").a ? rgba("Canvas") : { r: 255, g: 255, b: 255, a: 1 });
  }
  function fondo(el, incluirPropio = true) {
    const capas = [];
    for (let n = incluirPropio ? el : el.parentElement; n && n.nodeType === 1; n = n.parentElement) {
      const c = rgba(getComputedStyle(n).backgroundColor);
      if (c.a > 0) capas.push(c);
      if (c.a >= 1) break;
    }
    let color = capas.length && capas[capas.length - 1].a >= 1 ? capas.pop() : lienzo();
    while (capas.length) color = sobre(capas.pop(), color);
    return color;
  }
  function opacidad(el) {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity);
    return o;
  }

  // --- Visibilidad y nombres cortos ---
  const visible = el => {
    if (el.closest(".sr-only")) return false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  function nombre(el) {
    const uno = n => n.tagName.toLowerCase() + (n.id ? "#" + n.id : "") +
      [...n.classList].slice(0, 2).map(c => "." + c).join("");
    const partes = [uno(el)];
    for (let n = el.parentElement, i = 0; n && i < 2 && n !== document.body; n = n.parentElement, i++) {
      partes.unshift(uno(n));
      if (n.id) break;
    }
    return partes.join(" > ");
  }
  const muestra = el => (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 40);
  function agrupar(lista) {  // Mismo problema en el mismo tipo de elemento: una entrada (la primera) con su cuenta.
    const vistos = new Map();
    for (const item of lista) {
      const clave = JSON.stringify({ ...item, texto: undefined, ancho: undefined, derecha: undefined });
      if (vistos.has(clave)) vistos.get(clave).veces++;
      else vistos.set(clave, { ...item, veces: 1 });
    }
    return [...vistos.values()];
  }
  const textoDirecto = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());

  // --- 1. Desborde horizontal (RF-24) ---
  const desborde = [];
  if (document.documentElement.scrollWidth > W) {
    const desplazable = el => { for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
      const o = getComputedStyle(n).overflowX; if (o === "auto" || o === "scroll" || o === "hidden" || o === "clip") return true; } return false; };
    for (const el of document.body.querySelectorAll("*")) {
      if (!visible(el) || desplazable(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right > W + 0.5 || r.left < -0.5) desborde.push({ elemento: nombre(el), derecha: Math.round(r.right), ancho: W });
    }
    if (!desborde.length) desborde.push({ elemento: "html", derecha: document.documentElement.scrollWidth, ancho: W });
  }

  // --- 2. Controles pequeños (RF-25) ---
  const pequenos = [];
  const controles = new Set(document.querySelectorAll(
    "button, a[href], input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex='-1']), label"));
  for (const el of controles) {
    if (el.tagName === "LABEL" && !el.querySelector("input, select, textarea") && !el.control) continue;
    // Un campo dentro de su etiqueta, o escondido con una (casillas, el selector de urgencia), se mide por la etiqueta.
    if (el.matches("input, select, textarea") && el.labels && el.labels.length) {
      const r = el.getBoundingClientRect();
      if (opacidad(el) === 0 || r.width < 2 || r.height < 2 || el.closest("label")) continue;
    }
    if (!visible(el)) continue;
    if (el.tagName === "A" && getComputedStyle(el).display === "inline" && el.parentElement &&
        el.parentElement.textContent.trim().length > el.textContent.trim().length + 3) continue;  // Enlace dentro de un texto.
    const r = el.getBoundingClientRect();
    const ancho = Math.round(r.width * 10) / 10, alto = Math.round(r.height * 10) / 10;
    let falla;
    if (el.classList.contains("col")) falla = alto < 44;  // Excepción E1: columnas del gráfico, solo el alto.
    else if (tactil) falla = ancho < 44 || alto < 44;
    else falla = alto < 32;
    if (falla) pequenos.push({ elemento: nombre(el), ancho, alto, minimo: el.classList.contains("col") ? "alto 44" : tactil ? "44×44" : "alto 32", texto: muestra(el) });
  }

  // --- 3. Contraste (RF-27) ---
  const contraste = [];
  const deshabilitado = el => el.closest("[disabled], [aria-disabled='true']") !== null;
  function anotar(el, tipo, color, contra, minimo) {
    const valor = razon(color, contra);
    if (valor + 1e-6 < minimo) contraste.push({ elemento: nombre(el), tipo, color: hex(color), fondo: hex(contra), razon: Math.round(valor * 100) / 100, minimo, texto: muestra(el) });
  }
  for (const el of document.body.querySelectorAll("*")) {
    if (!visible(el) || deshabilitado(el)) continue;
    const cs = getComputedStyle(el);
    const grande = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && parseInt(cs.fontWeight, 10) >= 700);
    const base = fondo(el);
    const conAlfa = css => { const c = rgba(css); return { ...c, a: c.a * opacidad(el) }; };
    if (textoDirecto(el) || (el.matches("input, textarea, select") && el.value && !el.matches("[type=checkbox], [type=radio], [type=range], [type=color]"))) {
      anotar(el, "texto", sobre(conAlfa(cs.color), base), base, grande ? 3 : 4.5);
    }
    if (el.matches("input, textarea") && el.placeholder && !el.value) {
      anotar(el, "marcador", sobre(conAlfa(getComputedStyle(el, "::placeholder").color), base), base, 4.5);
    }
    if (el.matches("button, input:not([type=hidden]), select, textarea")) {
      // Borde de control: solo cuenta si el relleno no basta para distinguir el control de lo que lo rodea
      // (un botón con texto ya se reconoce por su texto).
      const detras = fondo(el, false);
      if (razon(base, detras) < 3 && parseFloat(cs.borderTopWidth) > 0) {
        const borde = rgba(cs.borderTopColor);
        if (borde.a > 0 && !(el.matches("button") && el.textContent.trim())) anotar(el, "borde", sobre({ ...borde, a: borde.a * opacidad(el) }, detras), detras, 3);
      }
    }
    if (el.tagName.toLowerCase() === "svg") {
      const forma = el.querySelector("path, rect, circle, line, polyline, polygon") || el;
      const fs = getComputedStyle(forma);
      const pintura = fs.stroke && fs.stroke !== "none" ? fs.stroke : fs.fill;
      if (pintura && pintura !== "none" && !pintura.startsWith("url(")) anotar(el, "icono", sobre(conAlfa(pintura), fondo(el, false)), fondo(el, false), 3);
    }
    if (el.classList.contains("seg")) {
      const detras = fondo(el, false);
      anotar(el, "dato", sobre(conAlfa(cs.backgroundColor), detras), detras, 3);
    }
  }

  // --- 4. Escala tipográfica (RF-11) ---
  const escala = [];
  for (const el of document.body.querySelectorAll("*")) {
    if (!visible(el)) continue;
    if (!textoDirecto(el) && !el.matches("input:not([type=checkbox]):not([type=radio]):not([type=range]), select, textarea")) continue;
    const px = Math.round(parseFloat(getComputedStyle(el).fontSize) * 100) / 100;
    if (!ESCALA.includes(px)) escala.push({ elemento: nombre(el), px, texto: muestra(el) });
  }

  return {
    contexto: { vista: location.hash || "#", ancho: W, alto: window.innerHeight, oscuro: matchMedia("(prefers-color-scheme: dark)").matches, tactil },
    desborde: agrupar(desborde),
    pequenos: agrupar(pequenos),
    contraste: agrupar(contraste),
    escala: agrupar(escala),
  };
}
