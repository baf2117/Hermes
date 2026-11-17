#!/usr/bin/env node
// Línea de estado de Claude Code: progreso de las tareas de la spec en curso.
// Lee specs/*/tasks.md (la fuente de verdad) y no escribe nada. Sin spec con tareas
// pendientes imprime una línea vacía. Nunca falla: ante cualquier error imprime vacío.
const fs = require('fs');
const path = require('path');

function readStdin() {
  try {
    if (process.stdin.isTTY) return {};
    return JSON.parse(fs.readFileSync(0, 'utf8'));
  } catch {
    return {};
  }
}

function parseTasks(text) {
  const lots = [];
  let current = { name: null, done: 0, total: 0 };
  lots.push(current);
  for (const line of text.split(/\r?\n/)) {
    const heading = line.match(/^##\s+(Lote\s+\S+)/i);
    if (heading) {
      current = { name: heading[1], done: 0, total: 0 };
      lots.push(current);
      continue;
    }
    const task = line.match(/^\s*- \[( |x|X)\]/);
    if (task) {
      current.total += 1;
      if (task[1] !== ' ') current.done += 1;
    }
  }
  return lots.filter((l) => l.total > 0);
}

function bar(done, total) {
  const filled = Math.floor((done * 10) / total);
  return '[' + '█'.repeat(filled) + '░'.repeat(10 - filled) + ']';
}

try {
  const input = readStdin();
  const base =
    (input.workspace && (input.workspace.project_dir || input.workspace.current_dir)) ||
    input.cwd ||
    process.cwd();
  const specsDir = path.join(base, 'specs');
  if (!fs.existsSync(specsDir)) process.exit(0);

  let best = null;
  for (const entry of fs.readdirSync(specsDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const file = path.join(specsDir, entry.name, 'tasks.md');
    if (!fs.existsSync(file)) continue;
    const lots = parseTasks(fs.readFileSync(file, 'utf8'));
    const total = lots.reduce((n, l) => n + l.total, 0);
    const done = lots.reduce((n, l) => n + l.done, 0);
    if (total === 0 || done === total) continue;
    const mtime = fs.statSync(file).mtimeMs;
    if (!best || mtime > best.mtime) best = { name: entry.name, lots, total, done, mtime };
  }
  if (!best) process.exit(0);

  const pct = Math.round((best.done * 100) / best.total);
  let out = `SDD ${best.name} ${bar(best.done, best.total)} ${best.done}/${best.total} (${pct}%)`;
  const named = best.lots.filter((l) => l.name);
  const lot = named.find((l) => l.done < l.total);
  if (lot) out += ` · ${lot.name} ${lot.done}/${lot.total}`;
  process.stdout.write(out);
} catch {
  // Sin salida: la línea de estado queda vacía.
}
