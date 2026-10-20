// PPA statistics probe. Runs in a browser on
//   https://www.pilbaraports.com.au/ports/port-of-port-hedland/about-port-of-hedland/port-statistics-reports
// (the site blocks non-browser clients). Paste into the devtools console; it returns a JSON object.
// Reads the two latest "commodity type" and two latest "destination" PDFs IN MEMORY and returns AGGREGATES ONLY:
// no vessel names, no rows. Output is copied by hand to results/s0/ppa_browser_probe.txt.
// Uses pdf.js 3.11.174 from cdnjs.
(async () => {
  if (!window.pdfjsLib) await new Promise((res, rej) => { const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'; s.onload = res; s.onerror = rej;
    document.documentElement.appendChild(s); });
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  const doc = new DOMParser().parseFromString(await (await fetch(location.pathname)).text(), 'text/html');
  const pdfs = [...doc.querySelectorAll('a')].map(a => a.getAttribute('href')).filter(h => h && /\.pdf$/i.test(h));
  const commodity = pdfs.filter(h => /commodity/i.test(h)).slice(0, 2);
  const destination = pdfs.filter(h => /destination/i.test(h)).slice(0, 2);

  // Rows = text items clustered by y (tolerance 4 pt), sorted by x.
  const rowsOf = async (u) => {
    const pdf = await pdfjsLib.getDocument({ data: await (await fetch(u)).arrayBuffer() }).promise;
    const out = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const tc = await (await pdf.getPage(i)).getTextContent();
      const it = tc.items.filter(t => t.str.trim()).map(t => ({ x: t.transform[4], y: t.transform[5], s: t.str.trim() }))
        .sort((a, b) => b.y - a.y);
      let cur = null;
      for (const t of it) { if (cur && Math.abs(cur.y - t.y) <= 4) cur.items.push(t); else { cur = { y: t.y, items: [t] }; out.push(cur); } }
    }
    return out.map(r => r.items.sort((a, b) => a.x - b.x).map(c => c.s));
  };
  const GROUPS = /^(Containers|Copper Concentrates|General|Hydrocarbon|Iron Ore|Manganese Ore|Salt|Spodumene Concentrate|Chemical Compound|Livestock|Chromite|Lithium)/;
  const DATE = /^\d{1,2}\/\d{1,2}\/\d{4}$/;
  const DATETIME = /\d{1,2}\/\d{1,2}\/\d{4}\s+\d{1,2}:\d{2}/;
  const mdy = s => { const [m, d, y] = s.split('/').map(Number); return { y, m, d }; };
  const stats = a => { const s = [...a].sort((p, q) => p - q); const q = f => s[Math.min(s.length - 1, Math.floor(f * (s.length - 1)))];
    return { n: s.length, min: s[0], p25: q(.25), median: q(.5), p75: q(.75), max: s[s.length - 1] }; };

  const commodityFile = async (u) => {
    const rows = await rowsOf(u);
    const head = rows.slice(0, 4).map(r => r.join(' ')).find(l => /date:/i.test(l)) || '';
    const hm = head.match(/(\d{2})\/(\d{2})\/(\d{4})\s+to\s+(\d{2})\/(\d{2})\/(\d{4})/);
    // Header range is D/M/Y here (e.g. 01/08/2026 to 31/08/2026); month = middle field.
    const fileMonth = hm ? { y: +hm[3], m: +hm[2] } : null;
    let grp = null; const recs = [];
    // Exclude the page footer ("Printed: <user>, <date> <time>"), which is a print timestamp, not a data field.
    const timeOfDay = rows.filter(r => !/Printed/i.test(r.join(' '))).some(r => DATETIME.test(r.join(' ')));
    for (const r of rows) {
      if (r.length <= 2 && GROUPS.test(r[0])) { grp = r[0].match(GROUPS)[0]; continue; }
      const d = r.filter(v => DATE.test(v));
      const n = r.filter(v => /^[\d,]+\.\d\d$/.test(v)).map(v => +v.replace(/,/g, ''));   // [import, export, GRT, DWT]
      if (d.length === 3) recs.push({ grp, key: r[0] + '|' + d[0], d: d.map(mdy), exp: n[1] });
    }
    const outside = (sel, k) => sel.filter(x => !(x.d[k].y === fileMonth.y && x.d[k].m === fileMonth.m)).length;
    const io = recs.filter(x => x.grp === 'Iron Ore');
    const calls = new Map(); io.forEach(x => calls.set(x.key, x.d));   // one entry per (vessel, arrival)
    const perDay = (k) => { const c = {}; for (const d of calls.values()) { const s = `${d[k].y}-${String(d[k].m).padStart(2, '0')}-${String(d[k].d).padStart(2, '0')}`; c[s] = (c[s] || 0) + 1; }
      const days = new Date(fileMonth.y, fileMonth.m, 0).getDate(); const inMonth = [];
      for (let i = 1; i <= days; i++) { const s = `${fileMonth.y}-${String(fileMonth.m).padStart(2, '0')}-${String(i).padStart(2, '0')}`; inMonth.push(c[s] || 0); }
      const hist = {}; inMonth.forEach(n => hist[n] = (hist[n] || 0) + 1);
      return { calls_dated_outside_month: Object.entries(c).filter(([s]) => !s.startsWith(`${fileMonth.y}-${String(fileMonth.m).padStart(2, '0')}`)).reduce((a, [, n]) => a + n, 0),
        per_day_in_month: stats(inMonth), days_with_n_calls: hist }; };
    return {
      file: u.split('/').pop(), header: head.slice(0, 80), file_month: fileMonth, time_of_day_in_any_date: timeOfDay,
      rows_all: recs.length, rows_iron_ore: io.length, iron_ore_calls: calls.size,
      iron_ore_export_t: io.reduce((a, x) => a + (x.exp || 0), 0),
      outside_month_all_rows: { arrival: outside(recs, 0), departure: outside(recs, 1), cargo_complete: outside(recs, 2) },
      outside_month_iron_ore_rows: { arrival: outside(io, 0), departure: outside(io, 1), cargo_complete: outside(io, 2) },
      iron_ore_calls_per_departure_day: perDay(1), iron_ore_calls_per_cargo_complete_day: perDay(2),
    };
  };
  const destinationFile = async (u) => {
    const rows = await rowsOf(u);
    const lines = rows.map(r => r.join(' '));
    // LOAD section: header row containing "Iron Ore", then the next "Total" row; zip by position.
    const iL = lines.findIndex(l => /^LOAD$/.test(l));
    const iH = lines.findIndex((l, i) => i > iL && /Iron Ore/.test(l));
    const iT = lines.findIndex((l, i) => i > iH && /^Total /.test(l));
    const names = lines[iH].replace(/ Total$/, '').split(/ (?=[A-Z])/).reduce((acc, w) => {   // re-join multi-word names
      if (acc.length && /^(Ore|Concentrates|Concentrate|Compound)$/.test(w)) acc[acc.length - 1] += ' ' + w; else acc.push(w); return acc; }, []);
    const vals = rows[iT].slice(1).map(v => +v.replace(/,/g, ''));
    return { file: u.split('/').pop(), date_headers: lines.filter(l => /date:/i.test(l)).map(l => l.slice(0, 80)),
      rows_with_a_date: rows.filter(r => r.some(v => DATE.test(v))).length,
      time_of_day_in_any_date: lines.filter(l => !/Printed/i.test(l)).some(l => DATETIME.test(l)),
      load_columns: names, load_iron_ore_total_t: vals[names.indexOf('Iron Ore')] };
  };
  const result = { checked_utc: new Date().toISOString(), commodity: [], destination: [] };
  for (const u of commodity) result.commodity.push(await commodityFile(u));
  for (const u of destination) result.destination.push(await destinationFile(u));
  return result;
})();
