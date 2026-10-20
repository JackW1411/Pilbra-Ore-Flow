// S3: PPA monthly iron-ore export totals, computed in the browser (the site blocks non-browser clients and Chrome
// allows only one automatic download per session). Run on
//   https://www.pilbaraports.com.au/ports/port-of-port-hedland/about-port-of-hedland/port-statistics-reports
// Returns AGGREGATES ONLY: per file, sha256 prefix, header month, total iron-ore export tonnes and line count.
// Row grouping as the S0 probe (text items clustered by y, 4 pt). Output copied to results/ppa_monthly_totals.txt.
(async () => {
  const pdfjs = await import('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs');
  pdfjs.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs';
  const GROUPS = /^(Containers|Copper Concentrates|General|Hydrocarbon|Iron Ore|Manganese Ore|Salt|Spodumene Concentrate|Chemical Compound|Livestock|Chromite|Lithium)/;
  const DATE = /^\d{1,2}\/\d{1,2}\/\d{4}$/, NUM = /^[\d,]+\.\d\d$/;
  const hrefs = [...new Set([...document.querySelectorAll('a')].map(a => a.href).filter(h => /commodity/i.test(h)))].slice(0, 8);
  const out = [];
  for (const h of hrefs) {
    const buf = await (await fetch(h)).arrayBuffer();
    const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buf.slice(0))))
      .map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
    const pdf = await pdfjs.getDocument({ data: buf }).promise;
    const rows = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const it = (await (await pdf.getPage(i)).getTextContent()).items.filter(t => t.str.trim())
        .map(t => ({ x: t.transform[4], y: t.transform[5], s: t.str.trim() })).sort((a, b) => b.y - a.y);
      let cur = null;
      for (const t of it) { if (cur && Math.abs(cur.y - t.y) <= 4) cur.items.push(t); else { cur = { y: t.y, items: [t] }; rows.push(cur); } }
    }
    const cells = rows.map(r => r.items.sort((a, b) => a.x - b.x).map(c => c.s));
    const head = cells.slice(0, 4).map(r => r.join(' ')).find(l => /date:/i.test(l)) || '';
    const hm = head.match(/(\d{2})\/(\d{2})\/(\d{4})\s+to\s+(\d{2})\/(\d{2})\/(\d{4})/);
    let grp = null, lines = 0, t = 0;
    for (const r of cells) {
      if (r.length <= 2 && GROUPS.test(r[0])) { grp = r[0].match(GROUPS)[0]; continue; }
      const d = r.filter(v => DATE.test(v)), n = r.filter(v => NUM.test(v)).map(v => +v.replace(/,/g, ''));
      if (d.length === 3 && grp === 'Iron Ore') { lines++; t += n[1]; }     // [import, export, GRT, DWT]
    }
    out.push(`${hm ? hm[3] + '-' + hm[2] : 'no-header'} sha256 ${sha} iron_ore_lines ${lines} iron_ore_export_t ${t.toFixed(2)}`);
  }
  return out.join('\n');
})();
