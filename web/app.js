/* Autopricer dashboard.
 *
 * Hand-built SVG and no framework: the server ships no bundler and assumes no
 * CDN. Chart marks follow one set of specs -- bars capped at 24px with a 4px
 * rounded data-end and a square baseline, 2px lines, >=8px markers carrying a
 * 2px surface ring, hairline gridlines, and a hover tooltip on every plotted
 * form.
 */
'use strict';

const SVG = 'http://www.w3.org/2000/svg';
const state = {
  meta: null, vmap: null, game: 'all', tab: 'sales', strategy: null,
  salesMetric: 'tickets_sold', listMetric: 'median_ask', cache: new Map(),
};

/* ------------------------------------------------------------------ utils */
const $ = (s) => document.querySelector(s);
const el = (t, a) => Object.assign(document.createElement(t), a || {});

function svgEl(tag, attrs) {
  const n = document.createElementNS(SVG, tag);
  for (const k in (attrs || {})) {
    if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
  }
  return n;
}

const money = (v, dp) => (v === null || v === undefined || Number.isNaN(Number(v)))
  ? '—'
  : '$' + Number(v).toLocaleString('en-US',
      { minimumFractionDigits: dp ?? 0, maximumFractionDigits: dp ?? 0 });

function compact(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
  if (Math.abs(n) >= 1e4) return '$' + (n / 1e3).toFixed(1) + 'K';
  return money(n);
}

const num = (v) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString('en-US');
const rowAlpha = (o) => (o >= 1 && o <= 26) ? String.fromCharCode(64 + o) : String(o);

/**
 * Fetch an API payload.
 *
 * When `window.AUTOPRICER_LOCAL` is present the same payloads are computed
 * in-page from an embedded snapshot instead of being fetched -- that is how the
 * standalone build works. Everything downstream is identical either way, so
 * the UI has one implementation rather than two.
 */
async function api(path) {
  if (state.cache.has(path)) return state.cache.get(path);
  let body;
  if (typeof window.AUTOPRICER_LOCAL === 'function') {
    body = window.AUTOPRICER_LOCAL(path); // throws Error on bad input
  } else {
    const r = await fetch(path);
    body = await r.json();
    if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
  }
  state.cache.set(path, body);
  return body;
}

const scoped = (base) =>
  base + (base.includes('?') ? '&' : '?') + 'event=' + encodeURIComponent(state.game);

/* ------------------------------------------------------------------ tooltip */
let tipNode = null;
function showTip(evt, title, rows) {
  if (!tipNode) tipNode = $('#tip');
  tipNode.innerHTML = `<div class="t">${title}</div>` + rows
    .map(([k, v]) => `<div class="r"><span>${k}</span><b>${v}</b></div>`).join('');
  tipNode.style.opacity = '1';
  moveTip(evt);
}
function moveTip(evt) {
  if (!tipNode) return;
  const pad = 14, r = tipNode.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
  tipNode.style.left = Math.max(8, x) + 'px';
  tipNode.style.top = Math.max(8, y) + 'px';
}
function hideTip() { if (tipNode) tipNode.style.opacity = '0'; }

function hoverable(node, title, rows) {
  node.addEventListener('mouseenter', (e) => showTip(e, title, rows));
  node.addEventListener('mousemove', moveTip);
  node.addEventListener('mouseleave', hideTip);
}

/* --------------------------------------------------------------- mark paths */
/** Bar/column path: 4px rounded on the data end, square at the baseline. */
function barPath(x, y, w, h, r, dir) {
  if (h <= 0 || w <= 0) return '';
  r = Math.max(0, Math.min(r, Math.min(w, h) / 2));
  if (dir === 'right') {
    return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r}`
         + ` V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`;
  }
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y}`
       + ` H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

function niceTicks(max, count) {
  if (!(max > 0)) return [0];
  const raw = max / (count || 4);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  // The last tick must sit at or above the data max: every chart scales its
  // marks by the top tick, so a top tick below the max would let the longest
  // bar run past the plot area and out of the card.
  const top = Math.ceil(max / step - 1e-9) * step;
  const out = [];
  for (let v = 0; v <= top + step * 1e-6; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}

function emptyNote(host, msg) {
  host.append(el('p', { className: 'empty', textContent: msg }));
}

/**
 * Width to lay a chart out in, measured from its container.
 *
 * Charts set their viewBox to this so one viewBox unit is one CSS pixel at
 * render time. Without it a chart in a wide card scales its viewBox up and
 * magnifies all the label text with it -- 11px axis labels came out at 20px in
 * a full-width card and at 8px in a half-width one.
 *
 * The host must already be in the document, or this measures 0.
 */
function hostWidth(host) {
  const w = host.clientWidth
    || (host.parentElement ? host.parentElement.clientWidth : 0);
  return Math.max(320, Math.round(w) || 720);
}

/* ------------------------------------------------------- horizontal bars */
function barsH(host, rows, opts) {
  const o = Object.assign({ fmt: num, barMax: 24, label: 'value' }, opts || {});
  host.textContent = '';
  if (!rows.length) return emptyNote(host, 'Nothing in scope.');

  const W = hostWidth(host), band = 26, gutter = 46;
  // Reserve the right margin from the widest value label, so the longest bar's
  // label still lands inside the chart instead of being pushed off the edge.
  const widest = Math.max(...rows.map((r) => String(o.fmt(r.value)).length));
  const right = Math.min(150, 14 + widest * 7);
  const H = rows.length * band + 26;
  const svg = svgEl('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': o.aria || o.label,
  });

  const ticks = niceTicks(Math.max(...rows.map((r) => r.value), 0), 4);
  const topTick = ticks[ticks.length - 1] || 1;
  const plotW = W - gutter - right;
  const x = (v) => gutter + (v / topTick) * plotW;

  ticks.forEach((t) => {
    svg.append(svgEl('line', { class: 'gridline', x1: x(t), x2: x(t), y1: 14, y2: H - 12 }));
    const lb = svgEl('text', { class: 'tick', x: x(t), y: 10, 'text-anchor': 'middle' });
    lb.textContent = o.tickFmt ? o.tickFmt(t) : num(t);
    svg.append(lb);
  });

  rows.forEach((r, i) => {
    const y = 18 + i * band;
    const th = Math.min(o.barMax, band - 8);
    const cy = y + th / 2 + 4;
    const w = Math.max(0, x(r.value) - gutter);
    svg.append(svgEl('path', { d: barPath(gutter, y, w, th, 4, 'right'),
      fill: 'var(--series-1)' }));

    const cat = svgEl('text', { class: 'catlabel', x: gutter - 8, y: cy, 'text-anchor': 'end' });
    cat.textContent = r.label;
    svg.append(cat);

    // Value at the tip, outside the bar, so it never needs clipping.
    const vl = svgEl('text', { class: 'dlabel', x: gutter + w + 8, y: cy });
    vl.textContent = o.fmt(r.value);
    svg.append(vl);

    const hit = svgEl('rect', { class: 'hit', x: 0, y: y - 3, width: W, height: band });
    hoverable(hit, r.tipTitle || r.label, r.tip || [[o.label, o.fmt(r.value)]]);
    if (r.onClick) hit.addEventListener('click', r.onClick);
    svg.append(hit);
  });

  svg.append(svgEl('line', { class: 'axisline', x1: gutter, x2: gutter, y1: 14, y2: H - 12 }));
  host.append(svg);
}

/* -------------------------------------------------------- vertical columns */
function colsV(host, rows, opts) {
  const o = Object.assign({ fmt: num, barMax: 24, label: 'value', labelEvery: 1 }, opts || {});
  host.textContent = '';
  if (!rows.length) return emptyNote(host, 'Nothing in scope.');

  const W = hostWidth(host), H = 240, left = 52, bottom = 34, top = 16;
  const svg = svgEl('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': o.aria || o.label,
  });
  const ticks = niceTicks(Math.max(...rows.map((r) => r.value), 0), 4);
  const topTick = ticks[ticks.length - 1] || 1;
  const plotH = H - bottom - top, plotW = W - left - 12;
  const y = (v) => top + plotH - (v / topTick) * plotH;
  const band = plotW / rows.length;

  ticks.forEach((t) => {
    svg.append(svgEl('line', { class: 'gridline', x1: left, x2: W - 12, y1: y(t), y2: y(t) }));
    const lb = svgEl('text', { class: 'tick', x: left - 8, y: y(t) + 4, 'text-anchor': 'end' });
    lb.textContent = o.tickFmt ? o.tickFmt(t) : num(t);
    svg.append(lb);
  });

  rows.forEach((r, i) => {
    const th = Math.min(o.barMax, Math.max(3, band - 2)); // 2px surface gap
    const cx = left + band * i + band / 2;
    svg.append(svgEl('path', {
      d: barPath(cx - th / 2, y(r.value), th, plotH - (y(r.value) - top), 4, 'up'),
      fill: 'var(--series-1)',
    }));
    if (i % o.labelEvery === 0) {
      const lb = svgEl('text', { class: 'catlabel', x: cx, y: H - bottom + 16,
        'text-anchor': 'middle' });
      lb.textContent = r.label;
      svg.append(lb);
    }
    const hit = svgEl('rect', { class: 'hit', x: cx - band / 2, y: top,
      width: band, height: plotH });
    hoverable(hit, r.tipTitle || r.label, r.tip || [[o.label, o.fmt(r.value)]]);
    svg.append(hit);
  });

  svg.append(svgEl('line', { class: 'axisline', x1: left, x2: W - 12,
    y1: top + plotH, y2: top + plotH }));
  host.append(svg);
}

/* ------------------------------------------------------------- line + area */
function lineChart(host, points, opts) {
  const o = Object.assign({ fmt: num, label: 'value' }, opts || {});
  host.textContent = '';
  if (points.length < 2) return emptyNote(host, 'Not enough days in scope to plot.');

  const W = hostWidth(host), H = 240, left = 52, bottom = 34, top = 16;
  const svg = svgEl('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': o.aria || o.label,
  });
  const ticks = niceTicks(Math.max(...points.map((p) => p.value), 0), 4);
  const topTick = ticks[ticks.length - 1] || 1;
  const plotH = H - bottom - top, plotW = W - left - 14;
  const x = (i) => left + (plotW * i) / (points.length - 1);
  const y = (v) => top + plotH - (v / topTick) * plotH;

  ticks.forEach((t) => {
    svg.append(svgEl('line', { class: 'gridline', x1: left, x2: W - 14, y1: y(t), y2: y(t) }));
    const lb = svgEl('text', { class: 'tick', x: left - 8, y: y(t) + 4, 'text-anchor': 'end' });
    lb.textContent = o.tickFmt ? o.tickFmt(t) : num(t);
    svg.append(lb);
  });

  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join(' ');
  svg.append(svgEl('path', {
    d: `${d} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`,
    fill: 'var(--series-1)', opacity: 0.10,
  }));
  svg.append(svgEl('path', { d, fill: 'none', stroke: 'var(--series-1)',
    'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));

  const every = Math.max(1, Math.ceil(points.length / 8));
  const last = points.length - 1;
  points.forEach((p, i) => {
    if (i % every && i !== last) return;
    // The forced final label would otherwise collide with the periodic one
    // just before it.
    if (i !== last && last - i < every * 0.6) return;
    const anchor = i === 0 ? 'start' : (i === last ? 'end' : 'middle');
    const lb = svgEl('text', { class: 'catlabel', x: x(i), y: H - bottom + 16,
      'text-anchor': anchor });
    lb.textContent = p.label;
    svg.append(lb);
  });

  const cross = svgEl('line', { x1: left, x2: left, y1: top, y2: top + plotH,
    stroke: 'var(--axis)', 'stroke-width': 1, opacity: 0 });
  // Parked on the first point rather than at the origin: a hidden mark still
  // counts toward the SVG's bounding box.
  const dot = svgEl('circle', { cx: x(0), cy: y(points[0].value), r: 5,
    fill: 'var(--series-1)', stroke: 'var(--surface-1)', 'stroke-width': 2, opacity: 0 });
  svg.append(cross, dot);

  const overlay = svgEl('rect', { class: 'hit', x: left, y: top, width: plotW, height: plotH });
  overlay.addEventListener('mousemove', (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(points.length - 1,
      Math.round(((px - left) / plotW) * (points.length - 1))));
    const p = points[i];
    cross.setAttribute('x1', x(i));
    cross.setAttribute('x2', x(i));
    cross.setAttribute('opacity', 1);
    dot.setAttribute('cx', x(i));
    dot.setAttribute('cy', y(p.value));
    dot.setAttribute('opacity', 1);
    showTip(e, p.label, p.tip || [[o.label, o.fmt(p.value)]]);
  });
  overlay.addEventListener('mouseleave', () => {
    cross.setAttribute('opacity', 0);
    dot.setAttribute('opacity', 0);
    hideTip();
  });
  svg.append(overlay);

  svg.append(svgEl('line', { class: 'axisline', x1: left, x2: W - 14,
    y1: top + plotH, y2: top + plotH }));
  host.append(svg);
}

/* -------------------------------------------------- two-series grouped cols */
function groupedCols(host, cats, series, opts) {
  const o = Object.assign({ fmt: money }, opts || {});
  host.textContent = '';
  if (!cats.length) return emptyNote(host, 'Nothing in scope.');

  const legend = el('div', { className: 'legend' });
  series.forEach((s) => {
    const k = el('span', { className: 'key' });
    const sw = el('span', { className: 'swatch' });
    sw.style.background = s.color;
    k.append(sw, el('span', { textContent: s.name }));
    legend.append(k);
  });
  host.append(legend);

  const W = hostWidth(host), H = 250, left = 56, bottom = 32, top = 18;
  const svg = svgEl('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': o.aria || 'grouped comparison',
  });
  const all = series.flatMap((s) => cats.map((c) => s.values[c] || 0));
  const ticks = niceTicks(Math.max(...all, 0), 4);
  const topTick = ticks[ticks.length - 1] || 1;
  const plotH = H - bottom - top, plotW = W - left - 12;
  const y = (v) => top + plotH - (v / topTick) * plotH;
  const band = plotW / cats.length;
  const th = Math.min(18, Math.max(3, (band - 2) / series.length - 2));

  ticks.forEach((t) => {
    svg.append(svgEl('line', { class: 'gridline', x1: left, x2: W - 12, y1: y(t), y2: y(t) }));
    const lb = svgEl('text', { class: 'tick', x: left - 8, y: y(t) + 4, 'text-anchor': 'end' });
    lb.textContent = o.tickFmt ? o.tickFmt(t) : money(t);
    svg.append(lb);
  });

  cats.forEach((c, i) => {
    const groupW = series.length * th + (series.length - 1) * 2; // 2px surface gap
    const x0 = left + band * i + (band - groupW) / 2;
    series.forEach((s, j) => {
      const v = s.values[c];
      if (!v) return;
      svg.append(svgEl('path', {
        d: barPath(x0 + j * (th + 2), y(v), th, plotH - (y(v) - top), 4, 'up'),
        fill: s.color,
      }));
    });
    const lb = svgEl('text', { class: 'catlabel', x: left + band * i + band / 2,
      y: H - bottom + 15, 'text-anchor': 'middle' });
    lb.textContent = c;
    svg.append(lb);

    const hit = svgEl('rect', { class: 'hit', x: left + band * i, y: top,
      width: band, height: plotH });
    hoverable(hit, (o.catLabel || '') + c,
      series.map((s) => [s.name, s.values[c] ? o.fmt(s.values[c]) : '—']));
    svg.append(hit);
  });

  svg.append(svgEl('line', { class: 'axisline', x1: left, x2: W - 12,
    y1: top + plotH, y2: top + plotH }));
  host.append(svg);
}

/* ------------------------------------------------------------------ seatmap */
const SEQ_STEPS = 7;

function seqStep(v, min, max) {
  if (v === null || v === undefined) return 0;
  if (!(max > min)) return 4;
  // Square-root scale: ticket counts and prices are both heavily right-skewed,
  // so a linear ramp would leave nearly every section in step 1.
  const t = Math.sqrt((v - min) / (max - min));
  return Math.min(SEQ_STEPS, Math.max(1, Math.ceil(t * SEQ_STEPS)));
}

function seatmap(host, valueBy, opts) {
  const o = Object.assign({ fmt: num, label: 'value' }, opts || {});
  host.textContent = '';
  const { layout, court } = state.vmap;

  const vals = Object.values(valueBy).filter((v) => v !== null && v !== undefined);
  const min = vals.length ? Math.min(...vals) : 0;
  const max = vals.length ? Math.max(...vals) : 0;

  const svg = svgEl('svg', {
    class: 'chart', viewBox: '0 0 100 100', preserveAspectRatio: 'xMidYMid meet',
    role: 'img', 'aria-label': o.aria || ('Target Center sections shaded by ' + o.label),
  });
  svg.style.maxHeight = '620px';

  svg.append(svgEl('rect', { x: court.x, y: court.y, width: court.w, height: court.h,
    rx: 1.2, fill: 'none', stroke: 'var(--axis)', 'stroke-width': 0.4 }));
  const ct = svgEl('text', { x: 50, y: court.y + court.h / 2 + 1.1,
    'text-anchor': 'middle', fill: 'var(--text-muted)', style: 'font-size:3px' });
  ct.textContent = 'COURT';
  svg.append(ct);

  const sizes = { lower: [4.0, 4.8], upper: [5.0, 5.2], floor: [3.0, 3.2] };
  const fonts = { lower: 2.1, upper: 2.3, floor: 1.9 };
  Object.entries(layout).forEach(([sec, pos]) => {
    const [w, h] = sizes[pos.tier] || [3.4, 4.6];
    const v = valueBy[sec];
    const has = v !== null && v !== undefined;
    const step = seqStep(v, min, max);
    const fill = has ? `var(--seq-${step})` : 'var(--seq-none)';
    const ink = has ? `var(--seq-${step}-ink)` : 'var(--seq-none-ink)';

    const g = svgEl('g', { transform: `translate(${pos.x} ${pos.y}) rotate(${pos.angle})` });
    g.append(svgEl('rect', { x: -w / 2, y: -h / 2, width: w, height: h, rx: 0.7, fill }));
    {
      // Counter-rotate the label so it stays upright: the tile is tangential
      // to the ring, but text at the bottom of the bowl would otherwise be
      // upside down. Label ink is chosen per fill step, so it always clears
      // contrast against its own tile.
      const t = svgEl('text', {
        transform: `rotate(${-pos.angle})`, x: 0, y: 0,
        'text-anchor': 'middle', 'dominant-baseline': 'central', fill: ink,
        style: `font-size:${fonts[pos.tier] || 2.3}px;font-weight:600`,
      });
      t.textContent = sec;
      g.append(t);
    }
    // Hit target overhangs the tile so small tiles stay easy to hover.
    const hit = svgEl('rect', { class: 'hit', x: -w / 2 - 0.4, y: -h / 2 - 0.4,
      width: w + 0.8, height: h + 0.8 });
    hoverable(hit, 'Section ' + sec,
      has ? (o.tip ? o.tip(sec) : [[o.label, o.fmt(v)]]) : [['—', 'no data in scope']]);
    if (has && o.onClick) hit.addEventListener('click', () => o.onClick(sec));
    g.append(hit);
    svg.append(g);
  });
  host.append(svg);

  const lg = el('div', { className: 'seqlegend' });
  lg.append(el('span', { textContent: o.legendLabel || o.label }));
  lg.append(el('span', { textContent: o.fmt(min) }));
  const steps = el('div', { className: 'steps' });
  for (let i = 1; i <= SEQ_STEPS; i++) {
    const s = el('i');
    s.style.background = `var(--seq-${i})`;
    steps.append(s);
  }
  lg.append(steps, el('span', { textContent: o.fmt(max) }),
    el('span', { textContent: '· grey = no data in scope' }));
  host.append(lg);
}

/* ------------------------------------------------------------------- tables */
function table(host, cols, rows) {
  host.textContent = '';
  const t = el('table');
  const thead = el('thead'), tr = el('tr');
  cols.forEach((c) => tr.append(el('th', { textContent: c.h })));
  thead.append(tr);
  const tb = el('tbody');
  rows.forEach((r) => {
    const x = el('tr');
    cols.forEach((c) => {
      const td = el('td');
      const v = c.get(r);
      if (v instanceof Node) td.append(v); else td.textContent = v;
      if (c.cls) td.className = c.cls;
      x.append(td);
    });
    tb.append(x);
  });
  t.append(thead, tb);
  host.append(t);
}

function tiles(host, items) {
  host.textContent = '';
  items.forEach((it) => {
    const d = el('div', { className: 'tile' });
    d.append(el('div', { className: 'lab', textContent: it.label }));
    d.append(el('div', { className: 'val' + (it.hero ? ' hero' : ''), textContent: it.value }));
    if (it.foot) d.append(el('div', { className: 'foot', textContent: it.foot }));
    host.append(d);
  });
}

function segmented(host, options, current, onPick) {
  host.textContent = '';
  options.forEach((o) => {
    const b = el('button', { className: 'toggle', type: 'button', textContent: o.label });
    b.setAttribute('aria-pressed', String(o.key === current));
    b.addEventListener('click', () => onPick(o.key));
    host.append(b);
  });
}

function sectionLink(sec) {
  const b = el('button', { className: 'linkish', textContent: sec });
  b.addEventListener('click', () => openSection(sec));
  return b;
}

/* =================================================================== SALES */
async function renderSales() {
  const d = await api(scoped('/api/sales'));
  const t = d.totals;

  tiles($('#sales-tiles'), [
    { label: 'Tickets sold', value: num(t.tickets_sold), hero: true,
      foot: `${num(t.sales)} sales in scope` },
    { label: 'Gross', value: compact(t.gross) },
    { label: 'Average price per ticket', value: money(t.avg_price) },
    { label: 'Sections with a sale', value: num(t.sections_with_sales) },
  ]);

  const metrics = [
    { key: 'tickets_sold', label: 'Tickets sold' },
    { key: 'gross', label: 'Gross' },
    { key: 'avg_price', label: 'Avg price' },
  ];
  segmented($('#sales-map-ctrls'), metrics, state.salesMetric, (k) => {
    state.salesMetric = k;
    renderSales();
  });

  const byS = {};
  d.sections.forEach((s) => { byS[s.section] = s; });
  const valueBy = {};
  d.sections.forEach((s) => { valueBy[s.section] = s[state.salesMetric]; });
  const mLabel = metrics.find((m) => m.key === state.salesMetric).label;
  const mFmt = state.salesMetric === 'tickets_sold' ? num
    : (state.salesMetric === 'gross' ? compact : money);

  seatmap($('#sales-map'), valueBy, {
    label: mLabel, legendLabel: mLabel + ':', fmt: mFmt,
    aria: `Target Center sections shaded by ${mLabel}`,
    tip: (sec) => {
      const s = byS[sec];
      return [['Tickets sold', num(s.tickets_sold)], ['Sales', num(s.sales)],
        ['Gross', money(s.gross)], ['Avg price', money(s.avg_price)],
        ['Price range', `${money(s.price.min)}–${money(s.price.max)}`]];
    },
    onClick: openSection,
  });

  const top = d.sections.slice(0, 14);
  $('#sales-bar-note').textContent =
    `Top ${top.length} of ${d.sections.length} sections with sales. Click a bar for row detail.`;
  barsH($('#sales-bar'), top.map((s) => ({
    label: s.section, value: s.tickets_sold, tipTitle: 'Section ' + s.section,
    tip: [['Tickets sold', num(s.tickets_sold)], ['Gross', money(s.gross)],
      ['Avg price', money(s.avg_price)]],
    onClick: () => openSection(s.section),
  })), { fmt: num, label: 'Tickets sold', aria: 'Top sections by tickets sold' });

  lineChart($('#sales-time'), d.by_day.map((r) => ({
    label: r.date.slice(5), value: r.tickets,
    tip: [['Date', r.date], ['Tickets', num(r.tickets)], ['Sales', num(r.sales)],
      ['Gross', money(r.gross)]],
  })), { fmt: num, label: 'Tickets', aria: 'Tickets sold per day' });

  colsV($('#sales-rows'), d.by_row.map((r) => ({
    label: r.row, value: r.tickets, tipTitle: 'Row ' + r.row,
    tip: [['Tickets', num(r.tickets)], ['Sales', num(r.sales)], ['Gross', money(r.gross)]],
  })), { fmt: num, label: 'Tickets', aria: 'Tickets sold by row' });

  table($('#sales-table'), [
    { h: 'Section', get: (r) => sectionLink(r.section), cls: 'sec' },
    { h: 'Tier', get: (r) => r.tier },
    { h: 'Sales', get: (r) => num(r.sales) },
    { h: 'Tickets', get: (r) => num(r.tickets_sold) },
    { h: 'Gross', get: (r) => money(r.gross) },
    { h: 'Avg price', get: (r) => money(r.avg_price) },
    { h: 'Low', get: (r) => money(r.price.min) },
    { h: 'High', get: (r) => money(r.price.max) },
    { h: 'Margin / ticket', get: (r) => money(r.margin_per_ticket) },
    { h: 'Rows', get: (r) => r.rows_sold.join(' ') || '—' },
  ], d.sections);
}

/* ================================================================ LISTINGS */
async function renderListings() {
  const d = await api(scoped('/api/listings'));
  const t = d.totals;

  tiles($('#list-tiles'), [
    { label: 'Live listings', value: num(t.listings), hero: true,
      foot: `${num(t.tickets_available)} tickets across ${num(t.sections_listed)} sections` },
    { label: 'Get-in price', value: money(t.get_in) },
    { label: 'Median ask', value: money(t.price.median) },
    { label: 'Ask range', value: `${money(t.price.min)}–${compact(t.price.max)}` },
  ]);

  const metrics = [
    { key: 'median_ask', label: 'Median ask' },
    { key: 'get_in', label: 'Get-in price' },
    { key: 'listings', label: 'Listing depth' },
  ];
  segmented($('#list-map-ctrls'), metrics, state.listMetric, (k) => {
    state.listMetric = k;
    renderListings();
  });

  const byS = {};
  d.sections.forEach((s) => { byS[s.section] = s; });
  const pick = (s) => state.listMetric === 'median_ask' ? s.price.median
    : (state.listMetric === 'get_in' ? s.get_in : s.listings);
  const valueBy = {};
  d.sections.forEach((s) => { valueBy[s.section] = pick(s); });
  const mLabel = metrics.find((m) => m.key === state.listMetric).label;
  const mFmt = state.listMetric === 'listings' ? num : money;

  seatmap($('#list-map'), valueBy, {
    label: mLabel, legendLabel: mLabel + ':', fmt: mFmt,
    aria: `Target Center sections shaded by ${mLabel}`,
    tip: (sec) => {
      const s = byS[sec];
      return [['Listings', num(s.listings)], ['Tickets', num(s.tickets_available)],
        ['Get-in', money(s.get_in)], ['Median ask', money(s.price.median)],
        ['Ask range', `${money(s.price.min)}–${money(s.price.max)}`],
        ['View score', s.view_score === null ? '—' : s.view_score]];
    },
    onClick: openSection,
  });

  const top = d.sections.slice(0, 14);
  $('#list-bar-note').textContent =
    `Dearest ${top.length} of ${d.sections.length} sections on the board. Click a bar for row detail.`;
  barsH($('#list-bar'), top.map((s) => ({
    label: s.section, value: s.price.median, tipTitle: 'Section ' + s.section,
    tip: [['Median ask', money(s.price.median)], ['Get-in', money(s.get_in)],
      ['Listings', num(s.listings)]],
    onClick: () => openSection(s.section),
  })), { fmt: money, tickFmt: money, label: 'Median ask', aria: 'Sections by median ask' });

  colsV($('#list-hist'), d.histogram.map((h) => ({
    label: h.high === null ? `${money(h.low)}+` : money(h.low),
    value: h.count,
    tipTitle: h.high === null ? `${money(h.low)} and up` : `${money(h.low)} – ${money(h.high)}`,
    tip: [['Listings', num(h.count)]],
  })), { fmt: num, label: 'Listings', aria: 'Ask price distribution' });

  table($('#list-table'), [
    { h: 'Section', get: (r) => sectionLink(r.section), cls: 'sec' },
    { h: 'Tier', get: (r) => r.tier },
    { h: 'Listings', get: (r) => num(r.listings) },
    { h: 'Tickets', get: (r) => num(r.tickets_available) },
    { h: 'Get-in', get: (r) => money(r.get_in) },
    { h: 'P25', get: (r) => money(r.price.p25) },
    { h: 'Median', get: (r) => money(r.price.median) },
    { h: 'P75', get: (r) => money(r.price.p75) },
    { h: 'Max', get: (r) => money(r.price.max) },
    { h: 'View score', get: (r) => r.view_score === null ? '—' : r.view_score },
  ], d.sections);
}

/* ------------------------------------------------------- section row detail */
async function openSection(sec) {
  const d = await api(scoped('/api/section/' + encodeURIComponent(sec)));
  const host = $('#panel-' + state.tab);
  host.querySelectorAll('.secdetail').forEach((n) => n.remove());
  const card = el('div', { className: 'card secdetail' });

  const head = el('div', { className: 'cardhead' });
  const left = el('div');
  left.append(el('h2', { textContent: `Section ${d.section} · ${d.tier} bowl` }));
  const soldTxt = d.sold.n
    ? `${money(d.sold.min)}–${money(d.sold.max)} (median ${money(d.sold.median)}, ${d.sold.n} sales)`
    : 'nothing in scope';
  left.append(el('p', { className: 'note',
    textContent: `Asks ${money(d.ask.min)}–${money(d.ask.max)} `
      + `(median ${money(d.ask.median)}, ${d.ask.n} listings) · sold ${soldTxt}` }));
  head.append(left);
  const close = el('button', { className: 'toggle', type: 'button', textContent: 'Close' });
  close.addEventListener('click', () => card.remove());
  head.append(close);
  card.append(head);

  // The card goes into the document before anything is drawn into it, so the
  // charts can measure their own width.
  const chart = el('div');
  const w = el('div', { className: 'tablewrap' });
  card.append(chart, w);
  host.append(card);

  groupedCols(chart, d.rows.map((r) => r.row), [
    { name: 'Median ask', color: 'var(--series-1)',
      values: Object.fromEntries(d.rows.map((r) => [r.row, r.ask.median])) },
    { name: 'Median sold', color: 'var(--series-2)',
      values: Object.fromEntries(d.rows.map((r) => [r.row, r.sold.median])) },
  ], { fmt: money, tickFmt: money, catLabel: 'Row ',
    aria: `Section ${d.section} median ask versus median sold, by row` });

  table(w, [
    { h: 'Row', get: (r) => r.row, cls: 'sec' },
    { h: 'Listings', get: (r) => num(r.ask.n) },
    { h: 'Ask low', get: (r) => money(r.ask.min) },
    { h: 'Ask median', get: (r) => money(r.ask.median) },
    { h: 'Ask high', get: (r) => money(r.ask.max) },
    { h: 'Sales', get: (r) => num(r.sold.n) },
    { h: 'Sold median', get: (r) => money(r.sold.median) },
  ], d.rows);

  const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
  card.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'nearest' });
}

/* =================================================================== QUOTE */
function boardStrip(host, q) {
  const r = q.recommendation;
  const comps = q.comps.closest.map((c) => c.adjusted);
  const lo = Math.min(r.price, r.range_low, r.expected_clear, ...comps);
  const hi = Math.max(r.price, r.range_high, r.expected_clear, ...comps);
  if (!(hi > lo)) return;

  const W = hostWidth(host), H = 96, pad = 30;
  const svg = svgEl('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': 'Where the recommendation sits among comparable asks',
  });
  const x = (v) => pad + ((v - lo) / (hi - lo)) * (W - pad * 2);

  svg.append(svgEl('line', { class: 'axisline', x1: pad, x2: W - pad, y1: 50, y2: 50 }));
  svg.append(svgEl('rect', { x: x(r.range_low), y: 42,
    width: Math.max(1, x(r.range_high) - x(r.range_low)), height: 16, rx: 4,
    fill: 'var(--series-1)', opacity: 0.10 }));

  q.comps.closest.forEach((c) => {
    const dot = svgEl('circle', { cx: x(c.adjusted), cy: 50, r: 5,
      fill: 'var(--series-1)', stroke: 'var(--surface-1)', 'stroke-width': 2 });
    hoverable(dot, `Section ${c.section} row ${c.row || '—'}`,
      [['Listed at', money(c.listed)], ['Adjusted to your seat', money(c.adjusted)],
        ['Quantity', c.qty], ['Same section', c.same_section ? 'yes' : 'no']]);
    svg.append(dot);
  });

  svg.append(svgEl('line', { x1: x(r.expected_clear), x2: x(r.expected_clear),
    y1: 34, y2: 66, stroke: 'var(--series-2)', 'stroke-width': 2, 'stroke-linecap': 'round' }));
  const ecl = svgEl('text', { x: x(r.expected_clear), y: 80, class: 'catlabel',
    'text-anchor': 'middle' });
  ecl.textContent = 'clears ~' + money(r.expected_clear);
  svg.append(ecl);

  svg.append(svgEl('path', { d: `M${x(r.price)},38 L${x(r.price) + 7},26 L${x(r.price) - 7},26 Z`,
    fill: 'var(--text-primary)' }));
  const pl = svgEl('text', { x: x(r.price), y: 20, class: 'dlabel', 'text-anchor': 'middle' });
  pl.textContent = money(r.price);
  svg.append(pl);
  host.append(svg);

  const lg = el('div', { className: 'legend' });
  [['var(--series-1)', 'Comparable asks, adjusted to your seat'],
    ['var(--series-2)', 'Expected clearing price']].forEach(([c, n]) => {
    const k = el('span', { className: 'key' });
    const sw = el('span', { className: 'swatch' });
    sw.style.background = c;
    k.append(sw, el('span', { textContent: n }));
    lg.append(k);
  });
  host.append(lg);
}

async function renderQuote() {
  const host = $('#quote');
  const section = $('#p-section').value.trim();
  if (!section) {
    host.innerHTML = '<div class="card"><p class="empty">Enter a section to get a quote.</p></div>';
    return;
  }
  const strategy = state.strategy || state.meta.default_strategy;
  let q;
  try {
    q = await api('/api/price?event=' + encodeURIComponent($('#p-game').value)
      + '&section=' + encodeURIComponent(section)
      + '&row=' + encodeURIComponent($('#p-row').value.trim())
      + '&qty=' + encodeURIComponent($('#p-qty').value || '2')
      + '&strategy=' + encodeURIComponent(strategy));
  } catch (e) {
    host.innerHTML = `<div class="card"><p class="empty err">${e.message}</p></div>`;
    return;
  }

  const r = q.recommendation, dr = q.drivers, rq = q.request;
  const confColor = { high: 'var(--good)', medium: 'var(--warning)',
    low: 'var(--critical)' }[r.confidence];

  host.textContent = '';
  const card = el('div', { className: 'card' });
  const grid = el('div', { className: 'quote' });

  const lhs = el('div');
  lhs.append(el('div', { className: 'lab', style: 'font-size:12px;color:var(--text-secondary)',
    textContent: rq.event_label }));
  lhs.append(el('div', { className: 'lab',
    style: 'font-size:12px;color:var(--text-muted);margin-bottom:2px',
    textContent: `Section ${rq.section}${rq.row ? ' · row ' + rq.row : ''} · `
      + `${rq.qty} ticket${rq.qty > 1 ? 's' : ''}` }));
  lhs.append(el('div', { className: 'val hero',
    style: 'font-size:48px;font-weight:600;letter-spacing:-0.02em;line-height:1.05',
    textContent: money(r.price) }));
  lhs.append(el('div', { style: 'font-size:12px;color:var(--text-muted);margin-top:2px',
    textContent: `per ticket · ${money(r.range_low)}–${money(r.range_high)} strategy range` }));

  const badges = el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;margin-top:12px' });
  const b1 = el('span', { className: 'badge' });
  const dot = el('span', { className: 'dot' });
  dot.style.background = confColor;
  b1.append(dot, el('span', { textContent: `${r.confidence} confidence` }));
  badges.append(b1,
    el('span', { className: 'badge',
      textContent: `${r.position.rank} cheapest of ${r.position.of_total} in section` }),
    el('span', { className: 'badge', textContent: `${rq.days_to_event} days out` }));
  lhs.append(badges);

  const ladder = el('div', { className: 'ladder' });
  state.meta.strategies.forEach((s) => {
    const b = el('button', { type: 'button' });
    b.setAttribute('aria-pressed', String(s === strategy));
    b.append(el('div', { className: 'k', textContent: s }));
    b.append(el('div', { className: 'v', textContent: money(r.ladder[s]) }));
    b.addEventListener('click', () => { state.strategy = s; renderQuote(); });
    ladder.append(b);
  });
  lhs.append(ladder);
  grid.append(lhs);

  const rhs = el('div');
  rhs.append(el('h2', { textContent: 'How this was built',
    style: 'font-size:14px;margin:0 0 10px' }));
  const dl = el('dl', { className: 'kv' });
  const put = (k, v) => dl.append(el('dt', { textContent: k }), el('dd', { textContent: v }));
  put('Game median ask, all sections', money(dr.event_ask_level));
  put(`Section ${rq.section} quality index`,
    `×${dr.section_index.toFixed(2)} (${dr.section_index_support_games} games)`);
  put(`Row ${rq.row || '—'} factor`, '×' + dr.row_factor.toFixed(2));
  put('→ Index model ask', money(dr.model_ask));
  put(`Live board median (${q.comps.adjusted.n} comps, row-adjusted)`, money(dr.market_ask));
  put(`→ Blended ask (board weight ${(dr.board_weight * 100).toFixed(0)}%)`,
    money(dr.blended_ask));
  put(`Clearing ratio, ${rq.tier} bowl`, '×' + dr.clearing_ratio.toFixed(2));
  put(`Comparable sales (${dr.sale_comp_basis.replace(/_/g, ' ')}, n=${dr.sale_comp_count})`,
    money(dr.sale_comp_median));
  put('→ Expected clearing price', money(r.expected_clear));
  rhs.append(dl);
  grid.append(rhs);
  card.append(grid);

  const strip = el('div', { style: 'margin-top:20px' });
  strip.append(el('h2', { textContent: 'Position on the board',
    style: 'font-size:14px;margin:0 0 2px' }));
  strip.append(el('p', { style: 'color:var(--text-muted);font-size:12px;margin:0 0 8px',
    textContent: 'Each dot is a live comparable ask re-priced as if it were your seat.' }));
  const stripPlot = el('div');
  strip.append(stripPlot);
  card.append(strip);

  if (q.caveats.length) {
    const cv = el('div', { className: 'caveats' });
    cv.append(el('div', { className: 'h', textContent: '⚠ Read before you list' }));
    const ul = el('ul');
    q.caveats.forEach((c) => ul.append(el('li', { textContent: c })));
    cv.append(ul);
    card.append(cv);
  }
  host.append(card);
  // Drawn after the card is in the document so it can measure its width.
  boardStrip(stripPlot, q);

  if (q.comps.closest.length) {
    const c1 = el('div', { className: 'card' });
    c1.append(el('h2', { textContent: 'Closest comparable asks' }));
    c1.append(el('p', { className: 'note',
      textContent: `Comp basis: ${q.comps.basis}. "Adjusted" re-prices each listing for your row`
        + (q.comps.basis === 'widened' ? ' and section.' : '.') }));
    const w = el('div', { className: 'tablewrap' });
    c1.append(w);
    table(w, [
      { h: 'Section', get: (c) => c.section, cls: 'sec' },
      { h: 'Row', get: (c) => c.row || '—' },
      { h: 'Qty', get: (c) => c.qty },
      { h: 'Listed at', get: (c) => money(c.listed) },
      { h: 'Adjusted to your seat', get: (c) => money(c.adjusted) },
      { h: 'Same section', get: (c) => c.same_section ? 'yes' : 'no' },
    ], q.comps.closest);
    host.append(c1);
  }

  if (q.sales_used.length) {
    const c2 = el('div', { className: 'card' });
    c2.append(el('h2', { textContent: 'Comparable sales used' }));
    c2.append(el('p', { className: 'note',
      textContent: `Basis: ${dr.sale_comp_basis.replace(/_/g, ' ')}.` }));
    const w = el('div', { className: 'tablewrap' });
    c2.append(w);
    table(w, [
      { h: 'Game', get: (s) => s.event, cls: 'sec' },
      { h: 'Section', get: (s) => s.section },
      { h: 'Row', get: (s) => s.row || '—' },
      { h: 'Qty', get: (s) => s.qty },
      { h: 'Price / ticket', get: (s) => money(s.price) },
      { h: 'Invoiced', get: (s) => s.invoice_date || '—' },
    ], q.sales_used);
    host.append(c2);
  }
}

/* =================================================================== MODEL */
async function renderModel() {
  const m = await api('/api/model');
  const host = $('#model-body');
  host.textContent = '';

  const c0 = el('div', { className: 'card' });
  c0.append(el('h2', { textContent: 'What the model learned' }));
  c0.append(el('p', { className: 'note',
    textContent: 'Fitted from the snapshot at start-up. All three surfaces are medians, '
      + 'so one silly ask cannot move them.' }));
  const dl = el('dl', { className: 'kv' });
  const put = (k, v) => dl.append(el('dt', { textContent: k }), el('dd', { textContent: v }));
  put('Clearing ratio (sale ÷ median ask, same game and section)',
    `×${m.clearing_ratio.toFixed(3)} (n=${m.clearing_ratio_samples})`);
  Object.entries(m.clearing_ratio_by_tier).forEach(([t, v]) =>
    put(`· ${t} bowl`, '×' + v.toFixed(3)));
  Object.entries(m.tier_index).forEach(([t, v]) =>
    put(`Typical ${t}-bowl section index`, '×' + v.toFixed(2)));
  c0.append(dl);
  host.append(c0);

  const c1 = el('div', { className: 'card' });
  c1.append(el('h2', { textContent: 'Section quality index' }));
  // Courtside runs x8-12 against a bowl that spans x0.4-2.9, so plotting all
  // of them on one linear axis flattens every bowl section to a stub. The
  // chart shows the bowl; the table below carries every section including the
  // floor.
  const floorIdx = Object.entries(m.section_index)
    .filter(([, v]) => v.tier === 'floor')
    .sort((a, b) => a[1].index - b[1].index);
  const floorNote = floorIdx.length
    ? ` Courtside (${floorIdx.map(([s]) => s).join(', ')}) runs `
      + `×${floorIdx[0][1].index.toFixed(1)}–×${floorIdx[floorIdx.length - 1][1].index.toFixed(1)}`
      + ' and is left off the chart so the bowl stays readable — it is in the table.'
    : '';
  c1.append(el('p', { className: 'note',
    textContent: 'Median ask in the section ÷ median ask across the whole game, then the '
      + 'median of that across games. ×1.00 is a typical seat.' + floorNote }));
  // Cards are attached before their charts are drawn, so each chart can
  // measure the width it will actually occupy.
  const bars = el('div');
  const w1 = el('div', { className: 'tablewrap' });
  c1.append(bars, w1);
  host.append(c1);

  const secs = Object.entries(m.section_index);
  const bowl = secs.filter(([, v]) => v.tier !== 'floor');
  barsH(bars, bowl.slice(0, 18).map(([s, v]) => ({
    label: s, value: v.index, tipTitle: 'Section ' + s,
    tip: [['Index', '×' + v.index.toFixed(3)], ['Tier', v.tier], ['Games', v.games]],
  })), { fmt: (v) => '×' + v.toFixed(2), tickFmt: (v) => '×' + v.toFixed(1),
    label: 'Index', aria: 'Section quality index for the bowl, highest first' });
  table(w1, [
    { h: 'Section', get: (r) => r[0], cls: 'sec' },
    { h: 'Tier', get: (r) => r[1].tier },
    { h: 'Index', get: (r) => '×' + r[1].index.toFixed(3) },
    { h: 'Games of support', get: (r) => num(r[1].games) },
  ], secs);

  Object.entries(m.row_curve).forEach(([tier, nodes]) => {
    const c = el('div', { className: 'card' });
    c.append(el('h2', { textContent: `Row curve · ${tier} bowl` }));
    c.append(el('p', { className: 'note',
      textContent: 'Ask ÷ the median ask of its own game-and-section cell, pooled by row '
        + 'depth, shrunk toward neutral by sample size, then fitted so a row is never '
        + 'worth less than one behind it.' }));
    const holder = el('div');
    c.append(holder);
    host.append(c);
    colsV(holder, nodes.map((n) => ({
      label: rowAlpha(n.row_ordinal), value: n.factor,
      tipTitle: 'Row ' + rowAlpha(n.row_ordinal),
      tip: [['Factor', '×' + n.factor.toFixed(3)], ['Listings at this row', num(n.n)]],
    })), { fmt: (v) => '×' + v.toFixed(2), tickFmt: (v) => '×' + v.toFixed(1),
      label: 'Factor', aria: `Row price factor, ${tier} bowl` });
    host.append(c);
  });

  const c3 = el('div', { className: 'card' });
  c3.append(el('h2', { textContent: 'Median ask by game' }));
  const est = m.event_level_estimated || [];
  c3.append(el('p', { className: 'note',
    textContent: 'The game level the index model is anchored to.'
      + (est.length
        ? ` ${est.join(', ')} has no active listings, so its level is implied`
          + ' from realised sales instead of measured from a board.'
        : '') }));
  const h3 = el('div');
  c3.append(h3);
  host.append(c3);
  colsV(h3, Object.entries(m.event_ask_level).map(([k, v]) => ({
    label: k.slice(5), value: v,
    tipTitle: (state.meta.events.find((e) => e.key === k) || {}).label || k,
    tip: [['Date', k], ['Median ask', money(v)]],
  })), { fmt: money, tickFmt: money, label: 'Median ask', labelEvery: 2,
    aria: 'Median ask by game' });
}

/* ==================================================================== shell */
const TABS = ['sales', 'listings', 'price', 'model'];
const RENDER = { sales: renderSales, listings: renderListings,
  price: renderQuote, model: renderModel };

function selectTab(name) {
  state.tab = name;
  TABS.forEach((n) => {
    $('#tab-' + n).setAttribute('aria-selected', String(n === name));
    $('#panel-' + n).hidden = n !== name;
  });
  RENDER[name]().catch((e) => {
    $('#panel-' + name).insertAdjacentHTML('afterbegin',
      `<div class="card"><p class="empty err">${e.message}</p></div>`);
  });
}

function wireTableToggle(btnSel, tableSel) {
  const btn = $(btnSel), tbl = $(tableSel);
  btn.addEventListener('click', () => {
    const on = tbl.hidden;
    tbl.hidden = !on;
    btn.setAttribute('aria-pressed', String(on));
    btn.textContent = on ? 'Hide table' : 'Show table';
  });
}

async function boot() {
  try {
    state.meta = await api('/api/meta');
    state.vmap = await api('/api/map');
  } catch (e) {
    document.body.insertAdjacentHTML('afterbegin',
      `<p class="wrap err">Could not reach the API: ${e.message}</p>`);
    return;
  }
  const m = state.meta;
  $('#snapshot').textContent = `${m.counts.events} home games · `
    + `${num(m.counts.listings)} live listings · ${num(m.counts.sales)} recorded sales · `
    + `clearing ratio ×${m.clearing_ratio}`;
  const bundle = window.AUTOPRICER_BUNDLE;
  $('#footnote').innerHTML = 'Listings are a single VividSeats snapshot; the sales span the '
    + 'weeks before it, so the clearing ratio mixes the ask-to-clear spread with price drift '
    + 'over that window. '
    + (bundle
      ? `Standalone build — the snapshot is baked in as of ${bundle.today} and cannot `
        + 'refresh itself. Re-pull it per <code>scripts/REFRESH.md</code>, then '
        + '<code>python3 scripts/build_artifact.py</code>.'
      : 'Refresh with <code>python3 -m autopricer refresh</code>.');

  const gsel = $('#gamesel'), psel = $('#p-game');
  gsel.textContent = '';
  psel.textContent = '';
  gsel.append(el('option', { value: 'all', textContent: `All ${m.counts.events} home games` }));
  m.events.forEach((e) => {
    const lab = `${e.key} · ${e.opponent}`
      + (e.game_type === 'regular' ? '' : ` (${e.game_type})`);
    gsel.append(el('option', { value: e.key, textContent: lab }));
    psel.append(el('option', { value: e.key, textContent: lab }));
  });
  m.sections.forEach((s) => $('#sectionlist').append(el('option', { value: s })));

  gsel.addEventListener('change', () => {
    state.game = gsel.value;
    document.querySelectorAll('.secdetail').forEach((n) => n.remove());
    RENDER[state.tab]();
  });
  TABS.forEach((n) => $('#tab-' + n).addEventListener('click', () => selectTab(n)));
  wireTableToggle('#sales-table-btn', '#sales-table');
  wireTableToggle('#list-table-btn', '#list-table');

  let t;
  const debounce = () => { clearTimeout(t); t = setTimeout(renderQuote, 260); };
  ['#p-section', '#p-row', '#p-qty'].forEach((s) =>
    $(s).addEventListener('input', debounce));
  $('#p-game').addEventListener('change', renderQuote);

  const btn = $('#themebtn');
  const current = () => document.documentElement.getAttribute('data-theme')
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const setTheme = (th) => {
    document.documentElement.setAttribute('data-theme', th);
    btn.textContent = th === 'dark' ? 'Light' : 'Dark';
    try { localStorage.setItem('autopricer-theme', th); } catch (e) { /* private mode */ }
  };
  let saved = null;
  try { saved = localStorage.getItem('autopricer-theme'); } catch (e) { /* private mode */ }
  if (saved) setTheme(saved);
  else btn.textContent = current() === 'dark' ? 'Light' : 'Dark';
  btn.addEventListener('click', () => {
    setTheme(current() === 'dark' ? 'light' : 'dark');
    document.querySelectorAll('.secdetail').forEach((n) => n.remove());
    RENDER[state.tab]();
  });

  // Charts are laid out in the pixel width measured at render time, so a
  // resize needs a redraw rather than an SVG rescale.
  let rz;
  let lastW = window.innerWidth;
  window.addEventListener('resize', () => {
    if (Math.abs(window.innerWidth - lastW) < 24) return;
    lastW = window.innerWidth;
    clearTimeout(rz);
    rz = setTimeout(() => RENDER[state.tab](), 180);
  });

  selectTab('sales');
}

boot();
