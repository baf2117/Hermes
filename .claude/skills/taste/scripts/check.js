#!/usr/bin/env node
// Comprobación de la fase 4 de la skill taste (autopsia anti-relleno), sin Python ni grep.
// Uso: node .claude/skills/taste/scripts/check.js docs/references/<dominio>/<dominio>
// Lee <base>.md y <base>.json, y comprueba: frases de relleno, las dos secciones y JSON
// válido. Solo lee, y solo dentro de docs/references/. Sale con 0 si todo pasa, 1 si no.
const fs = require('fs');
const path = require('path');

const BANNED =
  /clean|modern|sleek|visually appealing|user-friendly|intuitive|seamless|\belegant\b|minimalist|polished|refined|sophisticated|delightful|stunning|\bbeautiful\b|\bpremium\b/i;

function fail(msg) {
  process.stdout.write(msg + '\n');
  process.exit(1);
}

const arg = process.argv[2];
if (!arg) fail('Uso: node check.js docs/references/<dominio>/<dominio>');

const base = path.posix.normalize(arg.replace(/\\/g, '/').replace(/\.(md|json)$/i, ''));
if (!base.startsWith('docs/references/') || base.includes('..')) {
  fail('Ruta no permitida: solo se comprueba dentro de docs/references/.');
}

const mdFile = base + '.md';
const jsonFile = base + '.json';
let ok = true;
const report = [];

let md = null;
try {
  md = fs.readFileSync(mdFile, 'utf8');
} catch {
  report.push(`FALLA: no existe ${mdFile}`);
  ok = false;
}

if (md !== null) {
  const lines = md.split(/\r?\n/);
  const hits = [];
  lines.forEach((line, i) => {
    if (BANNED.test(line)) hits.push(`  ${i + 1}: ${line.trim().slice(0, 160)}`);
  });
  if (hits.length === 0) {
    report.push('Frases de relleno: 0 (pasa)');
  } else {
    ok = false;
    report.push(`Frases de relleno: ${hits.length} línea(s). Revísalas: dentro de una cita como foil valen; como descriptor positivo del diseño son relleno.`);
    report.push(...hits);
  }
  const sections = lines.filter((l) => /Design Map|Taste DNA/.test(l)).length;
  if (sections === 2) {
    report.push('Secciones Design Map y Taste DNA: 2 (pasa)');
  } else {
    ok = false;
    report.push(`FALLA: se esperaban 2 líneas con "Design Map" o "Taste DNA" y hay ${sections}`);
  }
}

try {
  JSON.parse(fs.readFileSync(jsonFile, 'utf8'));
  report.push('JSON: válido');
} catch (e) {
  ok = false;
  report.push(`FALLA: ${jsonFile} no es JSON válido o no existe (${e.message})`);
}

report.push(ok ? 'RESULTADO: OK' : 'RESULTADO: HAY QUE CORREGIR');
process.stdout.write(report.join('\n') + '\n');
process.exit(ok ? 0 : 1);
