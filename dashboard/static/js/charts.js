/**
 * Bark Dashboard — lightweight dependency-free SVG charts for the Statistics page.
 * No external chart library: renders inline <svg> so it works fully offline.
 */
(function () {
  'use strict';

  // Escape user-controlled strings used in HTML attribute/text positions.
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  const W = 560, H = 180, PAD = { top: 12, right: 12, bottom: 22, left: 42 };

  function niceMax(v) {
    if (!v) return 10;
    const pow = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / pow;
    const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return nice * pow;
  }

  /**
   * Line/area chart.
   * points: [{label, value}] (oldest -> newest). value may be null (gap).
   */
  function lineChart(el, points, opts) {
    opts = opts || {};
    if (!el || !points || points.length < 2) {
      if (el) el.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>Not enough data yet</strong><p>This chart fills in as daily snapshots are collected.</p></div></div>';
      return;
    }
    const iw = W - PAD.left - PAD.right;
    const ih = H - PAD.top - PAD.bottom;
    const vals = points.map(p => p.value).filter(v => v != null);
    const max = niceMax(Math.max.apply(null, vals));
    const min = 0;
    const range = Math.max(1, max - min);
    const stepX = iw / Math.max(1, points.length - 1);
    const coords = points.map((p, i) => {
      const x = PAD.left + (points.length === 1 ? 0 : i * stepX);
      const y = p.value == null ? null : H - PAD.bottom - ((p.value - min) / range) * ih;
      return { x: x, y: y, label: p.label, value: p.value };
    });

    let line = '';
    let area = '';
    let dots = '';
    coords.forEach((c, i) => {
      if (c.y == null) return;
      line += (i === 0 || coords[i - 1].y == null ? 'M' : 'L') + c.x.toFixed(1) + ',' + c.y.toFixed(1) + ' ';
      dots += '<circle cx="' + c.x.toFixed(1) + '" cy="' + c.y.toFixed(1) + '" r="2.4" fill="var(--accent)"><title>' + esc(c.label) + ': ' + esc(c.value) + '</title></circle>';
    });
    const first = coords.find(c => c.y != null);
    const last = coords.slice().reverse().find(c => c.y != null);
    if (first && last) {
      area = '<path d="M' + first.x.toFixed(1) + ',' + (H - PAD.bottom) + ' L' + first.x.toFixed(1) + ',' + first.y.toFixed(1) +
        ' ' + line.replace(/^M/, '') + 'L' + last.x.toFixed(1) + ',' + (H - PAD.bottom) + ' Z" fill="var(--accent)" opacity="0.12"></path>';
    }

    // Y gridlines + labels
    const yTicks = 4;
    let grid = '';
    for (let t = 0; t <= yTicks; t++) {
      const val = min + (range * t) / yTicks;
      const y = H - PAD.bottom - ((val - min) / range) * ih;
      grid += '<line x1="' + PAD.left + '" y1="' + y.toFixed(1) + '" x2="' + (W - PAD.right) + '" y2="' + y.toFixed(1) + '" stroke="var(--border-subtle)" stroke-width="1"></line>';
      grid += '<text x="' + (PAD.left - 6) + '" y="' + (y + 3).toFixed(1) + '" text-anchor="end" font-size="9" fill="var(--text-tertiary)">' + Math.round(val) + '</text>';
    }
    // X labels (first, middle, last)
    const xLabels = [coords[0], coords[Math.floor((coords.length - 1) / 2)], coords[coords.length - 1]];
    xLabels.forEach(c => {
      grid += '<text x="' + c.x.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="9" fill="var(--text-tertiary)">' + esc(c.label) + '</text>';
    });

    el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opts.label || 'Chart') + '" class="chart-svg">' + grid + area + '<path d="' + line.trim() + '" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"></path>' + dots + '</svg>';
    if (opts.valueLabel) {
      const lastV = points[points.length - 1];
      if (lastV && lastV.value != null) {
        const badge = document.createElement('div');
        badge.className = 'chart-current';
        badge.textContent = opts.valueLabel + ': ' + lastV.value;
        el.appendChild(badge);
      }
    }
  }

  /**
   * Horizontal bar chart.
   * data: [{label, value}]
   */
  function barChart(el, data, opts) {
    opts = opts || {};
    if (!el || !data || !data.length) {
      if (el) el.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No data</strong></div></div>';
      return;
    }
    const rows = data.slice(0, 10);
    const max = Math.max.apply(null, rows.map(r => r.value).concat([1]));
    const rowH = 22;
    // Reserve enough room for real Discord channel/emoji names and for the
    // value after a full-width bar. The former fixed 42px gutter clipped both.
    const longestLabel = rows.reduce((n, row) => Math.max(n, String(row.label || '').length), 0);
    const barPad = {
      left: Math.min(140, Math.max(58, longestLabel * 6 + 10)),
      right: 32,
    };
    const iw = W - barPad.left - barPad.right;
    const chartH = rows.length * rowH;
    let html = '<svg viewBox="0 0 ' + W + ' ' + chartH + '" role="img" aria-label="' + esc(opts.label || 'Chart') + '" class="chart-svg">';
    rows.forEach((r, i) => {
      const y = i * rowH;
      const bw = (r.value / max) * iw;
      html += '<text x="' + (barPad.left - 6) + '" y="' + (y + rowH / 2 + 3) + '" text-anchor="end" font-size="10" fill="var(--text-secondary)">' + esc(r.label) + '</text>';
      html += '<rect x="' + barPad.left + '" y="' + (y + 4) + '" width="' + Math.max(2, bw.toFixed(1)) + '" height="' + (rowH - 8) + '" rx="3" fill="var(--accent)" opacity="0.85"><title>' + esc(r.label) + ': ' + esc(r.value) + '</title></rect>';
      html += '<text x="' + (barPad.left + bw + 6) + '" y="' + (y + rowH / 2 + 3) + '" font-size="10" fill="var(--text-tertiary)">' + esc(r.value) + '</text>';
    });
    html += '</svg>';
    el.innerHTML = html;
  }

  /**
   * Pie / donut chart.
   * data: [{label, value}] — value must be > 0.
   */
  function pieChart(el, data, opts) {
    opts = opts || {};
    if (!el || !data || !data.length) {
      if (el) el.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No data</strong></div></div>';
      return;
    }
    const rows = data.filter(d => Number(d.value) > 0);
    const total = rows.reduce((s, r) => s + Number(r.value), 0);
    if (!total) {
      if (el) el.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No data</strong></div></div>';
      return;
    }
    const size = 180, cx = size / 2, cy = size / 2, r = 72;
    const palette = ['var(--accent)', '#e91e63', '#2ecc71', '#f1c40f', '#9b59b6', '#3498db', '#e67e22', '#1abc9c', '#e74c3c', '#607d8b'];
    let angle = -Math.PI / 2;
    let arcs = '';
    rows.forEach((row, i) => {
      const frac = Number(row.value) / total;
      const start = angle;
      const end = angle + frac * 2 * Math.PI;
      const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start);
      const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end);
      const large = frac > 0.5 ? 1 : 0;
      const color = palette[i % palette.length];
      arcs += '<path d="M' + cx + ',' + cy + ' L' + x1.toFixed(1) + ',' + y1.toFixed(1) + ' A' + r + ',' + r + ' 0 ' + large + ' 1 ' + x2.toFixed(1) + ',' + y2.toFixed(1) + ' Z" fill="' + color + '" opacity="0.88"><title>' + esc(row.label) + ': ' + esc(row.value) + '</title></path>';
      angle = end;
    });
    const legend = rows.map((row, i) => {
      const pct = total ? Math.round((Number(row.value) / total) * 100) : 0;
      return '<div class="chart-legend-item"><span class="chart-legend-swatch" style="background:' + palette[i % palette.length] + '"></span><span>' + esc(row.label) + '</span><span class="chart-legend-value">' + esc(row.value) + ' (' + pct + '%)</span></div>';
    }).join('');
    el.innerHTML = '<div class="pie-wrap"><svg viewBox="0 0 ' + size + ' ' + size + '" role="img" aria-label="' + esc(opts.label || 'Chart') + '" class="chart-svg chart-pie">' + arcs + '<text x="' + cx + '" y="' + (cy + 4) + '" text-anchor="middle" font-size="13" font-weight="700" fill="var(--text-primary)">' + esc(total) + '</text></svg><div class="chart-legend">' + legend + '</div></div>';
  }

  window.BarkCharts = { lineChart: lineChart, barChart: barChart, pieChart: pieChart, esc: esc };
})();
