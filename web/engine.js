/* In-page data layer for the standalone build.
 *
 * Serves byte-identical payloads to the Python API in autopricer/server.py, so
 * web/app.js is unchanged between the served app and the standalone page.
 *
 * The division of labour matters. The three fitted surfaces -- section index,
 * row curve, clearing ratios -- are NOT refitted here: they are computed by
 * the Python model (medians across games, sample-size shrinkage, the
 * pool-adjacent-violators monotone fit) and embedded verbatim in the bundle.
 * This file only does what a quote does on top of them: assemble a comp set,
 * blend two estimates, and pick a percentile. That keeps the hard statistics
 * in one tested place.
 *
 * scripts/verify_artifact.py diffs every payload this produces against the
 * Python server and fails the build on any mismatch.
 */
'use strict';

(function () {
  const B = window.AUTOPRICER_BUNDLE;
  if (!B) throw new Error('AUTOPRICER_BUNDLE missing');

  const S = B.surfaces;
  const P = B.params;

  /* ------------------------------------------------ normalize.py port */
  const BOWL_PREFIX =
    /^(lower|upper|club|suite|main|balcony|mezzanine)\s+(level|lvl)\s+/i;
  const NON_ROWS = new Set(
    ['', 'TBD', 'TBA', 'NONE', 'NULL', 'GA', 'PACKAGE', 'ZZ']);

  function sectionKey(raw) {
    if (raw === null || raw === undefined) return null;
    const s = String(raw).replace(BOWL_PREFIX, '').trim();
    if (!s || !/^[0-9]+$/.test(s)) return null;
    return s.replace(/^0+/, '') || null;
  }

  function rowKey(raw) {
    if (raw === null || raw === undefined) return null;
    const r = String(raw).trim().toUpperCase();
    return r || null;
  }

  function rowOrdinal(raw) {
    const r = rowKey(raw);
    if (r === null || NON_ROWS.has(r)) return null;
    if (/^[0-9]+$/.test(r)) {
      const n = parseInt(r, 10);
      return (n >= 1 && n <= 40) ? n : null;
    }
    if (r.length === 1 && r >= 'A' && r <= 'Z') return r.charCodeAt(0) - 64;
    return null;
  }

  function tierOf(section) {
    if (!section || !/^[0-9]+$/.test(section)) return null;
    const n = parseInt(section, 10);
    if (n < 100) return 'floor';
    if (n < 200) return 'lower';
    if (n < 300) return 'upper';
    return null;
  }

  /* ----------------------------------------------------- stats.py port */
  function pct(values, p) {
    if (!values.length) return null;
    const xs = values.slice().sort((a, b) => a - b);
    if (xs.length === 1) return xs[0];
    const q = Math.min(Math.max(p, 0), 1);
    const pos = q * (xs.length - 1);
    const lo = Math.floor(pos);
    const hi = Math.min(lo + 1, xs.length - 1);
    const frac = pos - lo;
    return xs[lo] * (1 - frac) + xs[hi] * frac;
  }
  const median = (v) => pct(v, 0.5);

  /**
   * Python's `round(x, dp)`, exactly.
   *
   * Python rounds the *exact* binary value of the double to the nearest
   * dp-decimal value, breaking true ties to even. Scaling by 10^dp and
   * inspecting the remainder does not reproduce that: the multiply introduces
   * its own error, so a value like 150.635 -- which is really
   * 150.63499999999999488... and rounds down in Python -- looks like a tie and
   * rounds up. That produced 78 one-cent disagreements with the API.
   *
   * So the rounding decision is made on the decimal expansion instead.
   * toFixed(40) is far beyond a double's resolution at these magnitudes, so
   * the digits past position dp settle the comparison unambiguously.
   */
  function r2(x, dp) {
    if (x === null || x === undefined) return null;
    if (typeof x !== 'number' || !Number.isFinite(x)) return x;
    dp = dp === undefined ? 2 : dp;

    const neg = x < 0;
    const s = Math.abs(x).toFixed(40);
    const dot = s.indexOf('.');
    const intPart = s.slice(0, dot);
    const frac = s.slice(dot + 1);
    const digits = (intPart + frac.slice(0, dp)).replace(/^0+(?=\d)/, '');
    const rest = frac.slice(dp);

    let roundUp;
    const first = rest.charAt(0);
    if (first > '5') roundUp = true;
    else if (first < '5') roundUp = false;
    else if (rest.slice(1).replace(/0+$/, '').length) roundUp = true;
    else {
      // A true tie: half to even, matching Python.
      const last = digits.charAt(digits.length - 1) || '0';
      roundUp = (Number(last) % 2) === 1;
    }

    let n = BigInt(digits.length ? digits : '0');
    if (roundUp) n += 1n;
    const out = Number(n) / Math.pow(10, dp);
    return neg ? -out : out;
  }

  function describe(values) {
    if (!values.length) {
      return { n: 0, min: null, p25: null, median: null,
               p75: null, max: null, mean: null };
    }
    const xs = values.slice().sort((a, b) => a - b);
    return {
      n: xs.length,
      min: r2(xs[0]),
      p25: r2(pct(xs, 0.25)),
      median: r2(pct(xs, 0.5)),
      p75: r2(pct(xs, 0.75)),
      max: r2(xs[xs.length - 1]),
      mean: r2(xs.reduce((a, b) => a + b, 0) / xs.length),
    };
  }

  /* ------------------------------------------------------ load the snapshot */
  function parseTsv(text) {
    const lines = text.split('\n').filter((l) => l.length);
    const head = lines[0].split('\t');
    return lines.slice(1).map((l) => {
      const parts = l.split('\t');
      const o = {};
      head.forEach((h, i) => { o[h] = parts[i] === undefined ? '' : parts[i]; });
      return o;
    });
  }

  const numOrNull = (v) => {
    if (v === '' || v === null || v === undefined) return null;
    const f = Number(v);
    return Number.isNaN(f) ? null : f;
  };

  const events = parseTsv(B.events_tsv).map((r) => ({
    key: r.event_date,
    event_date: r.event_date,
    opponent: r.opponent,
    label: r.label,
    vs_xid: r.vs_xid,
    game_type: r.game_type,
  }));
  events.sort((a, b) => a.key < b.key ? -1 : (a.key > b.key ? 1 : 0));
  const eventKeys = events.map((e) => e.key);
  const knownEvents = new Set(eventKeys);

  const listings = [];
  for (const r of parseTsv(B.listings_tsv)) {
    const sec = sectionKey(r.section);
    const t = tierOf(sec);
    const price = numOrNull(r.price);
    if (sec === null || t === null) continue;
    if (price === null || price <= 0) continue;
    if (!knownEvents.has(r.event_date)) continue;
    listings.push({
      event_date: r.event_date, section: sec, tier: t,
      row: rowKey(r.row), row_ord: rowOrdinal(r.row),
      price, qty: numOrNull(r.qty) === null ? 0 : Math.trunc(numOrNull(r.qty)),
      view_score: numOrNull(r.view_score),
    });
  }

  const sales = [];
  for (const r of parseTsv(B.sales_tsv)) {
    const sec = sectionKey(r.section);
    const t = tierOf(sec);
    const price = numOrNull(r.price);
    const qty = numOrNull(r.qty);
    if (sec === null || t === null) continue;
    if (!price || !qty || price <= 0 || qty <= 0) continue;
    if (!knownEvents.has(r.event_date)) continue;
    const cost = numOrNull(r.cost) || 0;
    // `net` is total_sales_ost / qty -- the broker's side of the sale, and the
    // figure Uptick shows. A 0 means the exchange never reported one, so it is
    // carried as unknown rather than as a sale that paid nothing.
    const net = numOrNull(r.net);
    sales.push({
      event_date: r.event_date, section: sec, tier: t,
      row: rowKey(r.row), row_ord: rowOrdinal(r.row),
      qty: Math.trunc(qty), price, cost,
      net: (net && net > 0) ? net : null,
      marketplace: (r.marketplace || '').trim() || 'unknown',
      invoice_date: r.invoice_date || null,
      sale_type: (r.sale_type || '').trim() || 'Unspecified',
      gross: price * Math.trunc(qty),
      // A recorded cost of 0 means "this POS did not capture cost", not a free
      // ticket, so margin stays unknown rather than becoming 100%.
      margin: cost > 0 ? price - cost : null,
    });
  }

  /* --------------------------------------------------------------- indices */
  function groupBy(rows, keyFn) {
    const m = new Map();
    for (const r of rows) {
      const k = keyFn(r);
      let a = m.get(k);
      if (!a) { a = []; m.set(k, a); }
      a.push(r);
    }
    return m;
  }

  const lByEvent = groupBy(listings, (l) => l.event_date);
  const lByEventSec = groupBy(listings, (l) => l.event_date + '|' + l.section);
  const lBySec = groupBy(listings, (l) => l.section);
  const sByEvent = groupBy(sales, (s) => s.event_date);
  const sByEventSec = groupBy(sales, (s) => s.event_date + '|' + s.section);
  const sBySec = groupBy(sales, (s) => s.section);

  const listingsFor = (ev, sec) => (sec === undefined || sec === null)
    ? (lByEvent.get(ev) || [])
    : (lByEventSec.get(ev + '|' + sec) || []);

  const allSections = (() => {
    const set = new Set();
    listings.forEach((l) => set.add(l.section));
    sales.forEach((s) => set.add(s.section));
    return [...set].sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  })();

  /* ---------------------------------------------- surface accessors (ported) */
  const indexOf = (sec) => {
    if (Object.prototype.hasOwnProperty.call(S.section_index, sec)) {
      return S.section_index[sec];
    }
    const t = tierOf(sec);
    return (t && S.tier_index[t] !== undefined) ? S.tier_index[t] : 1.0;
  };

  function rowFactor(tier, ord) {
    if (tier === null || ord === null || ord === undefined) return 1.0;
    const curve = S.row_curve[tier];
    if (!curve) return 1.0;
    if (curve[ord] !== undefined) return curve[ord];
    const known = Object.keys(curve).map(Number).sort((a, b) => a - b);
    if (!known.length) return 1.0;
    let best = known[0];
    for (const o of known) {
      if (Math.abs(o - ord) < Math.abs(best - ord)) best = o;
    }
    return curve[best];
  }

  const clearingRatioFor = (tier) =>
    (tier && S.tier_clear_ratio[tier] !== undefined)
      ? S.tier_clear_ratio[tier] : S.clear_ratio;

  /* ------------------------------------------------------- views.py port */
  function eventOverview() {
    const today = B.today;
    return events.map((ev) => {
      const ls = listingsFor(ev.key);
      const ss = sByEvent.get(ev.key) || [];
      const asks = ls.map((l) => l.price);
      const qty = ss.reduce((a, s) => a + s.qty, 0);
      const gross = ss.reduce((a, s) => a + s.gross, 0);
      return {
        event: ev.key, label: ev.label, opponent: ev.opponent,
        game_type: ev.game_type,
        days_to_event: daysBetween(today, ev.key),
        listings: ls.length,
        tickets_listed: ls.reduce((a, l) => a + l.qty, 0),
        sections_listed: new Set(ls.map((l) => l.section)).size,
        ask_median: asks.length ? r2(median(asks)) : null,
        ask_min: asks.length ? r2(Math.min(...asks)) : null,
        sales: ss.length,
        tickets_sold: qty,
        gross: r2(gross),
        avg_sale_price: ss.length ? r2(gross / qty) : null,
      };
    });
  }

  function daysBetween(fromIso, toIso) {
    const a = Date.UTC(...fromIso.split('-').map(Number).map((v, i) => i === 1 ? v - 1 : v));
    const b = Date.UTC(...toIso.split('-').map(Number).map((v, i) => i === 1 ? v - 1 : v));
    return Math.round((b - a) / 86400000);
  }

  const scopeOf = (ev) => (!ev || ev === 'all') ? null : ev;

  function salesBySection(eventRaw) {
    const ev = scopeOf(eventRaw);
    const rows = ev ? (sByEvent.get(ev) || []) : sales;

    const bySec = groupBy(rows, (s) => s.section);
    const sections = [...bySec.entries()].map(([sec, rs]) => {
      const qty = rs.reduce((a, s) => a + s.qty, 0);
      const gross = rs.reduce((a, s) => a + s.gross, 0);
      const margins = rs.filter((s) => s.margin !== null)
        .map((s) => s.margin * s.qty);
      const costKnownQty = rs.filter((s) => s.margin !== null)
        .reduce((a, s) => a + s.qty, 0);
      return {
        section: sec, tier: tierOf(sec), sales: rs.length,
        tickets_sold: qty, gross: r2(gross),
        avg_price: qty ? r2(gross / qty) : null,
        price: describe(rs.map((s) => s.price)),
        net: describe(rs.filter((s) => s.net !== null).map((s) => s.net)),
        margin_total: margins.length
          ? r2(margins.reduce((a, b) => a + b, 0)) : null,
        margin_per_ticket: costKnownQty
          ? r2(margins.reduce((a, b) => a + b, 0) / costKnownQty) : null,
        rows_sold: [...new Set(rs.filter((s) => s.row).map((s) => s.row))].sort(),
      };
    });
    sections.sort((a, b) => b.tickets_sold - a.tickets_sold);

    const bucket = (keyFn) => {
      const m = new Map();
      for (const s of rows) {
        const k = keyFn(s);
        if (k === null || k === undefined) continue;
        let b = m.get(k);
        if (!b) { b = { tickets: 0, gross: 0, sales: 0 }; m.set(k, b); }
        b.tickets += s.qty; b.gross += s.gross; b.sales += 1;
      }
      return m;
    };

    const byRow = [...bucket((s) => s.row || null).entries()]
      .sort((a, b) => a[0] < b[0] ? -1 : 1)
      .map(([row, b]) => ({ row, tickets: b.tickets, gross: r2(b.gross), sales: b.sales }));
    const byDay = [...bucket((s) => s.invoice_date).entries()]
      .sort((a, b) => a[0] < b[0] ? -1 : 1)
      .map(([date, b]) => ({ date, tickets: b.tickets, gross: r2(b.gross), sales: b.sales }));
    const byMarketplace = [...bucket((s) => s.marketplace).entries()]
      .sort((a, b) => b[1].tickets - a[1].tickets)
      .map(([marketplace, b]) => ({ marketplace, tickets: b.tickets,
        gross: r2(b.gross), sales: b.sales }));
    const byType = [...bucket((s) => s.sale_type).entries()]
      .sort((a, b) => b[1].tickets - a[1].tickets)
      .map(([type, b]) => ({ type, tickets: b.tickets, gross: r2(b.gross), sales: b.sales }));

    const totalQty = rows.reduce((a, s) => a + s.qty, 0);
    const totalGross = rows.reduce((a, s) => a + s.gross, 0);
    return {
      scope: ev || 'all',
      totals: {
        sales: rows.length, tickets_sold: totalQty, gross: r2(totalGross),
        avg_price: totalQty ? r2(totalGross / totalQty) : null,
        sections_with_sales: bySec.size,
        net_reported: rows.filter((s) => s.net !== null).length,
      },
      sections, by_row: byRow, by_day: byDay,
      by_marketplace: byMarketplace, by_type: byType,
    };
  }

  function listingsBySection(eventRaw) {
    const ev = scopeOf(eventRaw);
    const rows = ev ? listingsFor(ev) : listings;

    const bySec = groupBy(rows, (l) => l.section);
    const sections = [...bySec.entries()].map(([sec, rs]) => {
      const prices = rs.map((l) => l.price);
      const vs = rs.filter((l) => l.view_score !== null).map((l) => l.view_score);
      return {
        section: sec, tier: tierOf(sec), listings: rs.length,
        tickets_available: rs.reduce((a, l) => a + l.qty, 0),
        price: describe(prices),
        get_in: r2(Math.min(...prices)),
        view_score: vs.length ? r2(vs.reduce((a, b) => a + b, 0) / vs.length) : null,
        rows_listed: [...new Set(rs.filter((l) => l.row).map((l) => l.row))].sort(),
      };
    });
    sections.sort((a, b) => (b.price.median || 0) - (a.price.median || 0));

    const all = rows.map((l) => l.price);
    const edges = [0, 50, 100, 150, 200, 300, 400, 600, 900, 1500, 3000, 1e9];
    const histogram = [];
    for (let i = 0; i < edges.length - 1; i++) {
      const lo = edges[i], hi = edges[i + 1];
      histogram.push({
        low: lo, high: hi >= 1e9 ? null : hi,
        count: all.filter((x) => x >= lo && x < hi).length,
      });
    }
    return {
      scope: ev || 'all',
      totals: {
        listings: rows.length,
        tickets_available: rows.reduce((a, l) => a + l.qty, 0),
        sections_listed: bySec.size,
        price: describe(all),
        get_in: all.length ? r2(Math.min(...all)) : null,
      },
      sections, histogram,
    };
  }

  function sectionDetail(section, eventRaw) {
    const ev = scopeOf(eventRaw);
    const ls = ev ? listingsFor(ev, section) : (lBySec.get(section) || []);
    const ss = ev ? (sByEventSec.get(ev + '|' + section) || [])
      : (sBySec.get(section) || []);

    const keys = new Map();
    const push = (row, kind, v) => {
      const k = row || '?';
      let b = keys.get(k);
      if (!b) { b = { listings: [], sales: [], net: [] }; keys.set(k, b); }
      b[kind].push(v);
    };
    ls.forEach((l) => push(l.row, 'listings', l.price));
    ss.forEach((s) => { if (s.net !== null) push(s.row, 'net', s.net); });
    ss.forEach((s) => push(s.row, 'sales', s.price));

    const rows = [...keys.entries()].map(([row, b]) => ({
      row,
      row_ordinal: (() => {
        const hit = ls.find((l) => (l.row || '?') === row);
        return hit ? hit.row_ord : null;
      })(),
      ask: describe(b.listings),
      sold: describe(b.sales),
      net: describe(b.net),
    }));
    rows.sort((a, b) => {
      const an = a.row_ordinal === null, bn = b.row_ordinal === null;
      if (an !== bn) return an ? 1 : -1;
      const ao = a.row_ordinal || 0, bo = b.row_ordinal || 0;
      if (ao !== bo) return ao - bo;
      return a.row < b.row ? -1 : (a.row > b.row ? 1 : 0);
    });

    return {
      section, tier: tierOf(section), scope: ev || 'all',
      ask: describe(ls.map((l) => l.price)),
      sold: describe(ss.map((s) => s.price)),
      rows,
    };
  }

  /* ------------------------------------------------------- model.py port */
  function compSet(event, section, targetOrd) {
    const tier = tierOf(section);
    const rfTarget = rowFactor(tier, targetOrd);
    const notes = [];

    const adjust = (l, scale) => {
      const rfL = rowFactor(l.tier, l.row_ord);
      return {
        price: l.price * (scale === undefined ? 1 : scale) * (rfL ? rfTarget / rfL : 1),
        raw_price: l.price, section: l.section, row: l.row, qty: l.qty,
        same_section: l.section === section,
      };
    };

    const direct = listingsFor(event, section);
    let comps = direct.map((l) => adjust(l));
    if (comps.length >= P.min_comps) return { comps, basis: 'section', notes };

    const idxTarget = indexOf(section);
    const neighbours = [];
    for (const sec of allSections) {
      if (sec === section || tierOf(sec) !== tier) continue;
      const idx = indexOf(sec);
      if (!idx || !idxTarget) continue;
      const rel = Math.abs(idx - idxTarget) / idxTarget;
      if (rel <= P.neighbour_index_tol) neighbours.push([rel, sec]);
    }
    neighbours.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));

    for (const [, sec] of neighbours) {
      if (comps.length >= P.widen_target) break;
      const scale = idxTarget / indexOf(sec);
      comps = comps.concat(listingsFor(event, sec).map((l) => adjust(l, scale)));
    }

    if (direct.length < P.min_comps) {
      const used = [...new Set(comps.filter((c) => !c.same_section)
        .map((c) => c.section))].sort();
      if (used.length) {
        notes.push(`Only ${direct.length} live listing(s) in section ${section}; `
          + `comps widened to ${used.length} similar section(s) `
          + `(${used.join(', ')}), price-scaled by section index.`);
      } else {
        notes.push(`Only ${direct.length} live listing(s) in section ${section} and no `
          + 'comparable sections on the board; leaning on the index model.');
      }
    }
    return {
      comps,
      basis: direct.length >= P.min_comps ? 'section' : 'widened',
      notes,
    };
  }

  function saleComps(event, section, targetOrd) {
    const tier = tierOf(section);
    const rfTarget = rowFactor(tier, targetOrd);
    const lvlTarget = S.event_level[event];
    const rowAdj = (s) => {
      const rfS = rowFactor(s.tier, s.row_ord);
      return rfS ? rfTarget / rfS : 1;
    };

    const same = sByEventSec.get(event + '|' + section) || [];
    if (same.length) {
      return { vals: same.map((s) => s.price * rowAdj(s)),
               basis: 'event_section', n: same.length };
    }
    if (lvlTarget) {
      const across = sBySec.get(section) || [];
      let out = [];
      for (const s of across) {
        const lvl = S.event_level[s.event_date];
        if (lvl) out.push(s.price * rowAdj(s) * (lvlTarget / lvl));
      }
      if (out.length) return { vals: out, basis: 'section_all_games', n: out.length };

      const idxTarget = indexOf(section);
      out = [];
      for (const s of sales) {
        if (s.tier !== tier) continue;
        const lvl = S.event_level[s.event_date];
        const idxS = indexOf(s.section);
        if (lvl && idxS) {
          out.push(s.price * rowAdj(s) * (lvlTarget / lvl) * (idxTarget / idxS));
        }
      }
      if (out.length) return { vals: out, basis: 'tier_all_games', n: out.length };
    }
    return { vals: [], basis: 'none', n: 0 };
  }

  function salesDetail(event, section, basis) {
    if (basis === 'event_section') {
      return sByEventSec.get(event + '|' + section) || [];
    }
    const byDateDesc = (a, b) => {
      const x = a.invoice_date || '', y = b.invoice_date || '';
      return x < y ? 1 : (x > y ? -1 : 0);
    };
    if (basis === 'section_all_games') {
      return (sBySec.get(section) || []).slice().sort(byDateDesc);
    }
    if (basis === 'tier_all_games') {
      const tier = tierOf(section);
      return sales.filter((s) => s.tier === tier).slice().sort(byDateDesc);
    }
    return [];
  }

  function recommend(event, section, row, qty, strategyName) {
    const strategy = strategyName || P.default_strategy;
    const spec = P.strategies.find((s) => s[0] === strategy);
    if (!spec) {
      throw new Error(`unknown strategy '${strategy}'; expected one of `
        + `[${P.strategies.map((s) => `'${s[0]}'`).join(', ')}]`);
    }
    const ev = events.find((e) => e.key === event);
    if (!ev) throw new Error(`unknown event '${event}'`);
    const tier = tierOf(section);
    if (tier === null) {
      throw new Error(`'${section}' is not a Target Center seat section`);
    }

    const targetOrd = rowOrdinal(row);
    const rfTarget = rowFactor(tier, targetOrd);
    const idx = indexOf(section);
    const lvl = S.event_level[event];

    const caveats = [];
    if (S.event_level_estimated.indexOf(event) !== -1) {
      caveats.push('This game has no active listings in the snapshot, so there is no '
        + 'board to price against. The quote is built from realised sales '
        + 'for comparable seats and the game level implied by them — treat '
        + 'it as a starting point, not a market read.');
    }
    if (row && targetOrd === null) {
      caveats.push(`Row '${row}' has no readable depth, so the quote is for the `
        + 'section as a whole with no row adjustment.');
    }

    const cs = compSet(event, section, targetOrd);
    caveats.push(...cs.notes);
    const adj = cs.comps.map((c) => c.price).sort((a, b) => a - b);
    const direct = listingsFor(event, section);

    const marketAsk = median(adj);
    const modelAsk = lvl ? lvl * idx * rfTarget : null;
    const n = adj.length;
    let blendedAsk, w;
    if (marketAsk !== null && modelAsk !== null) {
      w = n / (n + P.comp_blend_k);
      blendedAsk = w * marketAsk + (1 - w) * modelAsk;
    } else {
      blendedAsk = marketAsk !== null ? marketAsk : modelAsk;
      w = marketAsk !== null ? 1.0 : 0.0;
    }
    if (blendedAsk === null || blendedAsk === undefined) {
      throw new Error(`no listings at all for ${event}; cannot price against an empty board`);
    }

    const clearRatio = clearingRatioFor(tier);
    const clearFromAsks = blendedAsk * clearRatio;
    const sc = saleComps(event, section, targetOrd);
    const saleMed = median(sc.vals);
    let expectedClear, ws;
    if (saleMed !== null) {
      ws = sc.n / (sc.n + P.sale_blend_k);
      expectedClear = ws * saleMed + (1 - ws) * clearFromAsks;
    } else {
      ws = 0.0;
      expectedClear = clearFromAsks;
    }

    const ceiling = pct(adj, P.max_comp_percentile);
    const priceAt = (targetPct, floorAtClear) => {
      let t = pct(adj, targetPct);
      if (t === null) t = blendedAsk;
      if (floorAtClear) t = Math.max(t, expectedClear);
      if (ceiling !== null) t = Math.min(t, Math.max(ceiling, expectedClear));
      return r2(t);
    };

    const ladder = {};
    P.strategies.forEach(([nm, p, floor]) => { ladder[nm] = priceAt(p, floor); });
    const price = ladder[strategy];
    const values = Object.values(ladder);
    const bandLo = Math.min(...values);
    const bandHi = Math.max(...values);

    if (ceiling !== null && price > ceiling + 0.01) {
      caveats.push(`The recommendation sits above the `
        + `${Math.trunc(P.max_comp_percentile * 100)}th percentile of comparable asks `
        + `(${fmtUsd(ceiling)}) because comparable seats have been clearing higher `
        + `(${fmtUsd(expectedClear)}). Expect a slower sale.`);
    }

    const listed = direct.map((l) => l.price).sort((a, b) => a - b);
    const cheaper = listed.filter((x) => x < price).length;

    let confidence;
    if (direct.length >= 8 && sc.n >= 3) confidence = 'high';
    else if (direct.length >= P.min_comps || sc.n >= 3) confidence = 'medium';
    else confidence = 'low';

    const closest = cs.comps.slice()
      .sort((a, b) => Math.abs(a.price - price) - Math.abs(b.price - price))
      .slice(0, 12)
      .map((c) => ({
        adjusted: r2(c.price), listed: r2(c.raw_price), section: c.section,
        row: c.row, qty: c.qty, same_section: c.same_section,
      }));

    return {
      request: {
        event, event_label: ev.label, opponent: ev.opponent,
        game_type: ev.game_type,
        days_to_event: daysBetween(B.today, event),
        section, row: row || null, row_ordinal: targetOrd, tier,
        qty: qty === undefined ? 2 : qty, strategy,
      },
      recommendation: {
        price, range_low: r2(bandLo), range_high: r2(bandHi),
        expected_clear: r2(expectedClear), confidence, ladder,
        position: {
          cheaper_in_section: cheaper,
          listings_in_section: listed.length,
          rank: cheaper + 1,
          of_total: listed.length + 1,
        },
      },
      drivers: {
        event_ask_level: lvl ? r2(lvl) : null,
        section_index: r2(idx, 4),
        section_index_support_games: S.section_index_support[section] || 0,
        row_factor: r2(rfTarget, 4),
        row_factor_support: (S.row_support[tier] || {})[targetOrd === null ? -1 : targetOrd] || 0,
        market_ask: marketAsk === null ? null : r2(marketAsk),
        model_ask: modelAsk === null ? null : r2(modelAsk),
        blended_ask: r2(blendedAsk),
        board_weight: r2(w, 3),
        clearing_ratio: r2(clearRatio, 4),
        sale_comp_basis: sc.basis,
        sale_comp_count: sc.n,
        sale_comp_median: saleMed === null ? null : r2(saleMed),
        sale_weight: r2(ws, 3),
      },
      comps: {
        basis: cs.basis,
        adjusted: describe(adj),
        listed_in_section: describe(listed),
        closest,
      },
      sales_used: salesDetail(event, section, sc.basis).slice(0, 12).map((s) => ({
        event: s.event_date, section: s.section, row: s.row, qty: s.qty,
        price: r2(s.price), net: s.net === null ? null : r2(s.net),
        marketplace: s.marketplace, invoice_date: s.invoice_date,
      })),
      caveats,
    };
  }

  // Matches Python's f"${x:,.2f}" for the two caveat strings that embed money.
  function fmtUsd(x) {
    return '$' + Number(r2(x)).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /* ---------------------------------------------------------- the dispatcher */
  const SECTION_RE = /^\/api\/section\/([^/]+)\/?$/;

  window.AUTOPRICER_LOCAL = function (path) {
    const [rawPath, rawQuery] = path.split('?');
    const q = new URLSearchParams(rawQuery || '');
    const one = (k) => q.get(k);

    if (rawPath === '/api/meta') return B.meta;
    if (rawPath === '/api/map') return B.map;
    if (rawPath === '/api/model') return B.model;
    if (rawPath === '/api/overview') return eventOverview();
    if (rawPath === '/api/sales') return salesBySection(one('event'));
    if (rawPath === '/api/listings') return listingsBySection(one('event'));

    const m = SECTION_RE.exec(rawPath);
    if (m) return sectionDetail(decodeURIComponent(m[1]), one('event'));

    if (rawPath === '/api/price') {
      const event = one('event'), section = one('section');
      if (!event || !section) throw new Error('event and section are required');
      const qtyRaw = one('qty') === null ? '2' : one('qty');
      if (!/^-?\d+$/.test(String(qtyRaw).trim())) {
        throw new Error(`qty must be a whole number, got '${qtyRaw}'`);
      }
      return recommend(event, section, one('row') || null,
        Math.max(1, parseInt(qtyRaw, 10)), one('strategy') || null);
    }
    throw new Error('not found');
  };

  // Exposed for scripts/verify_artifact.py.
  window.AUTOPRICER_DEBUG = { listings, sales, events, allSections };
})();
