/* __ETABS_IMPORT_IIFE__ */
(function () {
"use strict";
if (typeof window !== "undefined" && window.EtabsImport) return;
// etabs_import.js — lectores de archivos de ETABS.
// Reglas: no se inventa nada. Lo que no venga en el archivo se reporta como
// faltante y la UI lo muestra como tal.

const num = (v) => { const n = parseFloat(String(v).replace(',', '.')); return isFinite(n) ? n : null; };
const q = (line, key) => { // KEY "valor"
  const m = new RegExp(key + '\\s+"([^"]*)"', 'i').exec(line);
  return m ? m[1] : null;
};
const kv = (line, key) => { // KEY valor   (numérico, sin comillas)
  const m = new RegExp(key + '\\s+(-?[0-9.eE+]+)', 'i').exec(line);
  return m ? num(m[1]) : null;
};
const secDim = (name, fs) => {
  const f = fs && fs[name];
  if (f && f.b != null && f.h != null) return { b: f.b, h: f.h, from: 'FRAMESECTION' };
  const p = String(name || '').replace(/[^0-9Xx]/g, '').toUpperCase().split('X');
  const b = num(p[0]), h = num(p[1]);
  if (b != null && h != null) return { b, h, from: 'nombre' };
  return null;
};

function parseE2K(text, fileName) {
  const raw = String(text || '');
  const lines = raw.split(/\r?\n/);
  const out = {
    ok: false, file: fileName || '', program: null, version: null, units: null, title: null,
    stories: [], gx: [], gy: [], points: {}, sections: {}, beamLines: [], assigns: 0,
    beamsByStory: {}, cases: [], missing: [], warnings: [], counts: {},
  };
  if (!/\$\s*(PROGRAM INFORMATION|CONTROLS|STORIES|GRID|POINT COORDINATES|LINE CONNECTIVITIES)/i.test(raw)) {
    out.error = 'El archivo no tiene la estructura de un .e2k / .$et de ETABS (no se encontró ninguna sección «$ …»).';
    return out;
  }

  let sec = '';
  const stTop = [];
  const conn = [];
  const assigns = [];

  for (let i = 0; i < lines.length; i++) {
    const L = lines[i];
    if (/^\s*\$/.test(L)) { sec = L.replace(/^\s*\$\s*/, '').trim().toUpperCase(); continue; }
    if (!L.trim()) continue;

    if (/PROGRAM INFORMATION/.test(sec)) {
      const p = q(L, 'PROGRAM'); if (p) out.program = p;
      const v = q(L, 'VERSION'); if (v) out.version = v;
    } else if (/CONTROLS/.test(sec)) {
      const u = /UNITS\s+"([^"]*)"\s+"([^"]*)"(?:\s+"([^"]*)")?/i.exec(L);
      if (u) out.units = [u[1], u[2], u[3]].filter(Boolean).join(', ');
      const t = q(L, 'TITLE1'); if (t) out.title = t;
    } else if (/STORIES/.test(sec)) {
      const n = q(L, 'STORY'); if (n == null) continue;
      const h = kv(L, 'HEIGHT'), el = kv(L, 'ELEV');
      stTop.push({ n, h, elev: el });
    } else if (/GRID/.test(sec)) {
      const lab = q(L, 'LABEL'); if (lab == null) continue;
      const dir = (q(L, 'DIR') || '').toUpperCase();
      const c = kv(L, 'COORD') != null ? kv(L, 'COORD') : kv(L, 'ORDINATE');
      if (c == null) continue;
      if (dir === 'X') out.gx.push([lab, c]);
      else if (dir === 'Y') out.gy.push([lab, c]);
    } else if (/FRAME SECTIONS/.test(sec)) {
      const n = q(L, 'FRAMESECTION'); if (n == null) continue;
      out.sections[n] = {
        name: n, mat: q(L, 'MATERIAL'), shape: q(L, 'SHAPE'),
        h: kv(L, '\\bD') != null ? kv(L, '\\bD') * 100 : null,
        b: kv(L, '\\bB') != null ? kv(L, '\\bB') * 100 : null,
      };
    } else if (/POINT COORDINATES/.test(sec)) {
      const m = /POINT\s+"([^"]*)"\s+(-?[0-9.eE+]+)\s+(-?[0-9.eE+]+)/i.exec(L);
      if (m) out.points[m[1]] = { x: num(m[2]), y: num(m[3]) };
    } else if (/LINE CONNECTIVITIES/.test(sec)) {
      const m = /LINE\s+"([^"]*)"\s+(BEAM|COLUMN|BRACE)\s+"([^"]*)"\s+"([^"]*)"/i.exec(L);
      if (m) conn.push({ id: m[1], type: m[2].toUpperCase(), i: m[3], j: m[4] });
    } else if (/LINE ASSIGNS/.test(sec)) {
      const m = /LINEASSIGN\s+"([^"]*)"\s+"([^"]*)"/i.exec(L);
      if (m) assigns.push({ id: m[1], story: m[2], sec: q(L, 'SECTION') });
    } else if (/LOAD COMBINATIONS/.test(sec)) {
      const n = q(L, 'COMBO'); if (n && out.cases.indexOf(n) < 0) out.cases.push(n);
    }
  }

  // Elevaciones: el .e2k lista de arriba hacia abajo con HEIGHT de cada nivel.
  const base = stTop[stTop.length - 1];
  let z = (base && base.elev != null) ? base.elev : 0;
  const withElev = [];
  for (let i = stTop.length - 1; i >= 0; i--) {
    const s = stTop[i];
    if (s.h == null) { withElev.unshift({ n: s.n, h: null, elev: z, base: true }); continue; }
    z += s.h;
    withElev.unshift({ n: s.n, h: s.h, elev: Math.round(z * 1000) / 1000, base: false });
  }
  out.stories = withElev;                 // TODAS: incluye Base y sótanos (cotas negativas)
  out.baseName = base ? base.n : null;

  // Trabes con coordenadas resueltas
  const byId = {};
  conn.filter(c => c.type === 'BEAM').forEach(c => {
    const pi = out.points[c.i], pj = out.points[c.j];
    if (!pi || !pj) { out.warnings.push('La línea ' + c.id + ' referencia un punto inexistente.'); return; }
    const dir = Math.abs(pj.y - pi.y) < 1e-6 ? 'X' : (Math.abs(pj.x - pi.x) < 1e-6 ? 'Y' : 'D');
    const lab = (arr, v) => { const g = arr.filter(a => Math.abs(a[1] - v) < 1e-6)[0]; return g ? g[0] : null; };
    const line = dir === 'X' ? lab(out.gy, pi.y) : dir === 'Y' ? lab(out.gx, pi.x) : null;
    const a = dir === 'X' ? lab(out.gx, Math.min(pi.x, pj.x)) : lab(out.gy, Math.min(pi.y, pj.y));
    const b = dir === 'X' ? lab(out.gx, Math.max(pi.x, pj.x)) : lab(out.gy, Math.max(pi.y, pj.y));
    byId[c.id] = {
      id: c.id, dir, line, a, b,
      x1: Math.min(pi.x, pj.x), y1: Math.min(pi.y, pj.y),
      x2: dir === 'X' ? Math.max(pi.x, pj.x) : pi.x,
      y2: dir === 'Y' ? Math.max(pi.y, pj.y) : pi.y,
    };
    out.beamLines.push(byId[c.id]);
  });

  out.assigns = assigns.length;
  assigns.forEach(a => {
    const g = byId[a.id]; if (!g) return;                 // columnas y otros: se ignoran
    (out.beamsByStory[a.story] = out.beamsByStory[a.story] || []).push(
      Object.assign({}, g, { sec: a.sec, story: a.story }));
  });

  // Reporte honesto de lo que sí y lo que no vino en el archivo
  if (!out.stories.length) out.missing.push('Niveles ($ STORIES)');
  if (!out.gx.length || !out.gy.length) out.missing.push('Ejes en ambas direcciones ($ GRIDS)');
  if (!Object.keys(out.points).length) out.missing.push('Coordenadas de nudos ($ POINT COORDINATES)');
  if (!out.beamLines.length) out.missing.push('Conectividad de trabes ($ LINE CONNECTIVITIES)');
  if (!Object.keys(out.beamsByStory).length) out.missing.push('Asignación de trabes por nivel ($ LINE ASSIGNS)');
  if (!Object.keys(out.sections).length) out.missing.push('Secciones ($ FRAME SECTIONS)');
  out.missing.push('Elementos mecánicos (M3, V2) — un .e2k no contiene resultados de análisis');

  // Secciones sin dimensiones legibles
  Object.keys(out.sections).forEach(k => {
    const d = secDim(k, out.sections);
    if (!d) out.warnings.push('No se pudieron leer las dimensiones de la sección «' + k + '».');
    else { out.sections[k].b = d.b; out.sections[k].h = d.h; out.sections[k].dimFrom = d.from; }
  });

  out.counts = {
    stories: out.stories.length,
    grids: out.gx.length + out.gy.length,
    points: Object.keys(out.points).length,
    beams: out.beamLines.length,
    beamAssigns: Object.keys(out.beamsByStory).reduce((a, k) => a + out.beamsByStory[k].length, 0),
    sections: Object.keys(out.sections).length,
    cases: out.cases.length,
  };
  out.ok = out.counts.beamAssigns > 0 && out.counts.grids > 0;
  if (!out.ok && !out.error) out.error = 'El archivo se leyó pero no contiene trabes asignadas a niveles.';
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
//  OAPI — modelo abierto en ETABS (solo dentro de la app de escritorio).
//  El puente de Python expone dos slots; aquí solo se normaliza su respuesta a
//  la MISMA forma que producen los lectores de archivo, para que la UI tenga un
//  único modelo de datos.
// ─────────────────────────────────────────────────────────────────────────────
const bridge = () => (typeof window !== 'undefined' ? window.struxBridge : null);
function oapiAvailable() { const b = bridge(); return !!(b && b.etabs_model && b.etabs_frame_forces); }

function ask(slot, payload) {
  return new Promise((res, rej) => {
    const b = bridge();
    if (!b || !b[slot]) { rej(new Error('El puente OAPI no está disponible en esta vista: requiere la aplicación de escritorio de Strux con ETABS abierto.')); return; }
    let done = false;
    const to = setTimeout(() => { if (!done) { done = true; rej(new Error('ETABS no respondió (' + slot + '). Verifica que el modelo esté abierto y con el análisis corrido.')); } }, 30000);
    try {
      b[slot](JSON.stringify(payload || {}), (json) => {
        if (done) return; done = true; clearTimeout(to);
        try {
          const o = JSON.parse(json || '{}');
          if (o && o.error) rej(new Error(String(o.error)));
          else res(o);
        } catch (e) { rej(new Error('El puente devolvió una respuesta ilegible.')); }
      });
    } catch (e) { done = true; clearTimeout(to); rej(new Error('No se pudo invocar el puente OAPI: ' + e.message)); }
  });
}

// Geometría por OAPI. Espera del puente:
// { program, version, units, title, file,
//   stories:[{name, height, elev}],            ← GetStories
//   gx:[[label,coord]], gy:[[label,coord]],    ← GetGridSys / CoordSys
//   sections:{name:{b,h,mat,shape}},           ← PropFrame.GetRectangle (cm)
//   beams:[{id, story, section, xi,yi, xj,yj}] ← FrameObj.GetPoints + GetLabelFromName
// }
function fromOapiModel(p) {
  const out = {
    ok: false, file: p.file || 'modelo abierto en ETABS', program: p.program || 'ETABS', version: p.version || null,
    units: p.units || null, title: p.title || null, source: 'oapi',
    stories: [], gx: p.gx || [], gy: p.gy || [], points: {}, sections: p.sections || {},
    beamLines: [], assigns: 0, beamsByStory: {}, cases: p.cases || [], missing: [], warnings: [], counts: {},
  };
  (p.stories || []).forEach(s => out.stories.push({ n: s.name, h: s.height == null ? null : s.height, elev: s.elev, base: !!s.base }));
  (p.beams || []).forEach(b => {
    const dir = Math.abs(b.yj - b.yi) < 1e-6 ? 'X' : (Math.abs(b.xj - b.xi) < 1e-6 ? 'Y' : 'D');
    const lab = (arr, v) => { const g = (arr || []).filter(a => Math.abs(a[1] - v) < 1e-6)[0]; return g ? g[0] : null; };
    const g = {
      id: b.id, dir, story: b.story, sec: b.section,
      line: dir === 'X' ? lab(out.gy, b.yi) : dir === 'Y' ? lab(out.gx, b.xi) : null,
      a: dir === 'X' ? lab(out.gx, Math.min(b.xi, b.xj)) : lab(out.gy, Math.min(b.yi, b.yj)),
      b: dir === 'X' ? lab(out.gx, Math.max(b.xi, b.xj)) : lab(out.gy, Math.max(b.yi, b.yj)),
      x1: Math.min(b.xi, b.xj), y1: Math.min(b.yi, b.yj),
      x2: dir === 'X' ? Math.max(b.xi, b.xj) : b.xi,
      y2: dir === 'Y' ? Math.max(b.yi, b.yj) : b.yi,
    };
    out.beamLines.push(g);
    (out.beamsByStory[b.story] = out.beamsByStory[b.story] || []).push(g);
    out.assigns++;
  });
  Object.keys(out.sections).forEach(k => { const d = secDim(k, out.sections); if (d) { out.sections[k].b = d.b; out.sections[k].h = d.h; out.sections[k].dimFrom = d.from; } });
  if (!out.stories.length) out.missing.push('Niveles (Story data)');
  if (!out.gx.length || !out.gy.length) out.missing.push('Ejes en ambas direcciones');
  out.missing.push('Elementos mecánicos — se piden por frame al abrir la ventana de diseño');
  out.counts = {
    stories: out.stories.length, grids: out.gx.length + out.gy.length,
    points: 0, beams: out.beamLines.length, beamAssigns: out.assigns,
    sections: Object.keys(out.sections).length, cases: out.cases.length,
  };
  out.ok = out.assigns > 0 && out.counts.grids > 0;
  if (!out.ok) out.error = 'ETABS respondió sin trabes asignadas a niveles.';
  return out;
}
function requestModel() { return ask('etabs_model', {}).then(fromOapiModel); }

// Resultados por OAPI: SapModel.Results.FrameForce por frame (lazy).
// Espera { frames:[{name, station:[], loadCase:[], p:[], v2:[], m3:[]}] }
function fromOapiFrameForce(p, story) {
  const out = { ok: false, file: 'ETABS · Results.FrameForce', source: 'oapi', cases: [], stories: story ? [story] : [], byKey: {}, rows: 0, missing: [], warnings: [], table: 'FrameForce (OAPI)' };
  const cs = {};
  (p.frames || []).forEach(f => {
    const st = f.station || [], lc = f.loadCase || [], m3 = f.m3 || [], v2 = f.v2 || [], pp = f.p || [];
    const n = Math.min(st.length, lc.length, m3.length);
    if (!n) { out.warnings.push('ETABS no devolvió estaciones para ' + f.name + '.'); return; }
    for (let i = 0; i < n; i++) {
      const key = (f.story || story || '') + '|' + f.name;
      const b = (out.byKey[key] = out.byKey[key] || {});
      (b[lc[i]] = b[lc[i]] || []).push({ x: +st[i], M: +m3[i], V: v2[i] == null ? 0 : +v2[i], P: pp[i] == null ? 0 : +pp[i] });
      cs[lc[i]] = 1; out.rows++;
    }
  });
  Object.keys(out.byKey).forEach(k => Object.keys(out.byKey[k]).forEach(oc => out.byKey[k][oc].sort((a, b) => a.x - b.x)));
  out.cases = Object.keys(cs);
  out.frames = Object.keys(out.byKey).length;
  out.ok = out.rows > 0;
  if (!out.ok) out.error = 'ETABS no devolvió resultados. Revisa que el análisis esté corrido y que las combinaciones estén seleccionadas para salida.';
  return out;
}
function requestFrameForces(story, frames, cases) {
  return ask('etabs_frame_forces', { story, frames, cases }).then(o => fromOapiFrameForce(o, story));
}

function parseFrameForces(text, fileName) {
  const raw = String(text || '');
  const lines = raw.split(/\r?\n/).filter(l => l.trim() !== '');
  const out = { ok: false, file: fileName || '', cases: [], stories: [], byKey: {}, rows: 0, missing: [], warnings: [], table: null };
  if (!lines.length) { out.error = 'El archivo está vacío.'; return out; }

  const split = (l) => (l.indexOf('\t') >= 0 ? l.split('\t') : l.split(',')).map(s => s.trim().replace(/^"|"$/g, ''));
  let hi = -1, head = null;
  for (let i = 0; i < Math.min(lines.length, 12); i++) {
    if (/^TABLE:/i.test(lines[i])) { out.table = (/"([^"]*)"/.exec(lines[i]) || [])[1] || null; continue; }
    const c = split(lines[i]).map(s => s.toLowerCase());
    if (c.indexOf('station') >= 0 && (c.indexOf('m3') >= 0 || c.indexOf('v2') >= 0)) { hi = i; head = split(lines[i]); break; }
  }
  if (hi < 0) {
    out.error = 'No se encontró el encabezado de la tabla. Se esperan las columnas Story, Beam, Output Case, Station, V2 y M3 (exporta «Element Forces - Beams» desde ETABS).';
    return out;
  }
  const idx = {};
  head.forEach((h, k) => { idx[h.toLowerCase().replace(/\s+/g, '')] = k; });
  const need = ['story', 'outputcase', 'station', 'm3'];
  const lack = need.filter(n => idx[n] == null);
  if (lack.length) { out.error = 'Faltan columnas obligatorias en la tabla: ' + lack.join(', ') + '.'; return out; }
  const iBeam = idx.beam != null ? idx.beam : (idx.uniquename != null ? idx.uniquename : null);
  if (iBeam == null) { out.error = 'La tabla no trae la columna Beam ni UniqueName: no se puede ligar cada renglón a un frame.'; return out; }

  const cs = {}, sts = {};
  for (let i = hi + 1; i < lines.length; i++) {
    const c = split(lines[i]);
    const story = c[idx.story], beam = c[iBeam], oc = c[idx.outputcase];
    const x = num(c[idx.station]), M = num(c[idx.m3]);
    if (!story || !beam || !oc || x == null || M == null) continue;   // renglón de unidades u hoja vacía
    const V = idx.v2 != null ? num(c[idx.v2]) : null;
    const P = idx.p != null ? num(c[idx.p]) : null;
    const key = story + '|' + beam;
    const b = (out.byKey[key] = out.byKey[key] || {});
    (b[oc] = b[oc] || []).push({ x, M, V: V == null ? 0 : V, P: P == null ? 0 : P });
    cs[oc] = (cs[oc] || 0) + 1; sts[story] = 1; out.rows++;
  }
  Object.keys(out.byKey).forEach(k => Object.keys(out.byKey[k]).forEach(oc => out.byKey[k][oc].sort((p, r) => p.x - r.x)));
  out.cases = Object.keys(cs);
  out.stories = Object.keys(sts);
  if (idx.v2 == null) out.missing.push('Columna V2 (cortante) — los diagramas de cortante no se pueden trazar');
  if (idx.p == null) out.missing.push('Columna P (axial)');
  out.frames = Object.keys(out.byKey).length;
  out.ok = out.rows > 0;
  if (!out.ok) out.error = 'La tabla no trae renglones legibles.';
  return out;
}

// ── Publicación global (script clásico: funciona con <script src> desde file://) ──
(function (g) {
  g.EtabsImport = {
    parseE2K: parseE2K,
    parseFrameForces: parseFrameForces,
    oapiAvailable: oapiAvailable,
    fromOapiModel: fromOapiModel,
    requestModel: requestModel,
    fromOapiFrameForce: fromOapiFrameForce,
    requestFrameForces: requestFrameForces,
  };
})(typeof window !== 'undefined' ? window : this);

})();
