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

  const W = 560, H = 190, PAD = { top: 14, right: 14, bottom: 26, left: 46 };

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
    const color = opts.color || 'var(--accent)';
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
      dots += '<circle cx="' + c.x.toFixed(1) + '" cy="' + c.y.toFixed(1) + '" r="3" fill="' + color + '" stroke="var(--bg-card-solid)" stroke-width="1.2"><title>' + esc(c.label) + ': ' + esc(c.value) + '</title></circle>';
    });
    const first = coords.find(c => c.y != null);
    const last = coords.slice().reverse().find(c => c.y != null);
    if (first && last) {
      area = '<path d="M' + first.x.toFixed(1) + ',' + (H - PAD.bottom) + ' L' + first.x.toFixed(1) + ',' + first.y.toFixed(1) +
        ' ' + line.replace(/^M/, '') + 'L' + last.x.toFixed(1) + ',' + (H - PAD.bottom) + ' Z" fill="' + color + '" opacity="0.14"></path>';
    }

    // Y gridlines + labels
    const yTicks = 4;
    let grid = '';
    for (let t = 0; t <= yTicks; t++) {
      const val = min + (range * t) / yTicks;
      const y = H - PAD.bottom - ((val - min) / range) * ih;
      grid += '<line x1="' + PAD.left + '" y1="' + y.toFixed(1) + '" x2="' + (W - PAD.right) + '" y2="' + y.toFixed(1) + '" stroke="var(--border-subtle)" stroke-width="1"></line>';
      grid += '<text x="' + (PAD.left - 7) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end" font-size="11" font-weight="600" fill="var(--text-tertiary)">' + Math.round(val) + '</text>';
    }
    // X labels (first, middle, last)
    const xLabels = [coords[0], coords[Math.floor((coords.length - 1) / 2)], coords[coords.length - 1]];
    xLabels.forEach(c => {
      grid += '<text x="' + c.x.toFixed(1) + '" y="' + (H - 7) + '" text-anchor="middle" font-size="11" font-weight="500" fill="var(--text-tertiary)">' + esc(c.label) + '</text>';
    });

    el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opts.label || 'Chart') + '" class="chart-svg">' + grid + area + '<path d="' + line.trim() + '" fill="none" stroke="' + color + '" stroke-width="2.5" stroke-linejoin="round"></path>' + dots + '</svg>';
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
      if (el) el.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>' + esc(opts.emptyTitle || 'No data yet') + '</strong>' + (opts.emptyHint ? '<p>' + esc(opts.emptyHint) + '</p>' : '') + '</div></div>';
      return;
    }
    const rows = data.slice(0, 10);
    const max = Math.max.apply(null, rows.map(r => r.value).concat([1]));
    const rowH = 26;
    const hasAvatars = rows.some(r => r.avatar);
    const hasEmoji = rows.some(r => r.emoji);
    // Reserve enough room for the image + a gap + the full label + the value
    // after a full-width bar. The label is placed to the RIGHT of the image so
    // the two never overlap, and it is TRUNCATED to fit the gutter so a very
    // long name can never spill over the bar/value.
    const imgW = hasEmoji ? 16 : (hasAvatars ? 13.2 : 0);
    const imgGap = imgW ? 6 : 0;
    const longestLabel = rows.reduce((n, row) => Math.max(n, String(row.label || '').length), 0);
    // Approx label pixel width at 12px font (~6.5px/char) + a small stub.
    const labelW = longestLabel * 6.5 + 12;
    const gutterBase = hasEmoji ? 70 : (hasAvatars ? 76 : 64);
    const barPad = {
      left: Math.min(170, Math.max(gutterBase, imgW + imgGap + labelW)),
      right: 36,
    };
    // Max label length that fits between the image and the bar (avoid overlap).
    // The image is anchored at the LEFT of the gutter; the label fills the
    // space between the image's right edge and the bar. Use a conservative
    // ~7.2px/char so wide glyphs never spill over the bar/value.
    const imgX = 2;                                  // left gutter origin for the image
    const labelStart = imgX + imgW + imgGap;         // where the label text begins
    const labelArea = barPad.left - labelStart - 4;  // px available for the label
    const maxLabelChars = Math.max(4, Math.floor(labelArea / 7.2));
    const clipLabel = (s) => {
      const str = String(s == null ? '' : s);
      return str.length > maxLabelChars ? str.slice(0, maxLabelChars - 1) + '…' : str;
    };
    const iw = W - barPad.left - barPad.right;
    const chartH = rows.length * rowH;
    const baseColor = opts.color || 'var(--accent)';
    const gradId = 'bar-grad-' + Math.random().toString(36).slice(2, 8);
    let html = '<svg viewBox="0 0 ' + W + ' ' + chartH + '" role="img" aria-label="' + esc(opts.label || 'Chart') + '" class="chart-svg">'
      + '<defs><linearGradient id="' + gradId + '" x1="0" y1="0" x2="1" y2="0">'
      + '<stop offset="0%" stop-color="' + baseColor + '"></stop>'
      + '<stop offset="100%" stop-color="' + baseColor + '" stop-opacity="0.62"></stop>'
      + '</linearGradient></defs>';
    rows.forEach((r, i) => {
      const y = i * rowH;
      const bw = (r.value / max) * iw;
      let labelX = barPad.left - 7;
      let anchor = 'end';
      if (r.emoji) {
        // Emoji image at the left of the gutter, then the label to its right
        // (start-anchored) so the name never draws over the emoji.
        const emX = imgX;
        const emY = y + (rowH - 16) / 2;
        html += '<image x="' + emX + '" y="' + emY + '" width="16" height="16" preserveAspectRatio="xMidYMid meet" href="' + esc(r.emoji) + '"></image>';
        labelX = labelStart;
        anchor = 'start';
      } else if (r.avatar) {
        // Avatar (circular clip) at the left of the gutter, then the label
        // to its right (start-anchored).
        const clipId = 'clip-' + i + '-' + (r.id || i);
        const avX = imgX + 6.6;
        const avY = y + rowH / 2;
        html += '<circle cx="' + avX + '" cy="' + avY + '" r="7.5" fill="var(--bg-card-solid)" stroke="' + baseColor + '" stroke-width="1"></circle>';
        html += '<defs><clipPath id="' + esc(clipId) + '"><circle cx="' + avX + '" cy="' + avY + '" r="6.6"></circle></clipPath></defs>';
        html += '<image x="' + (avX - 6.6) + '" y="' + (avY - 6.6) + '" width="13.2" height="13.2" preserveAspectRatio="xMidYMid slice" clip-path="url(#' + esc(clipId) + ')" href="' + esc(r.avatar) + '"></image>';
        labelX = labelStart;
        anchor = 'start';
      }
      html += '<text x="' + labelX + '" y="' + (y + rowH / 2 + 3.5) + '" text-anchor="' + anchor + '" font-size="12" font-weight="500" fill="var(--text-secondary)">' + esc(clipLabel(r.label)) + '</text>';
      html += '<rect x="' + barPad.left + '" y="' + (y + 4) + '" width="' + Math.max(2, bw.toFixed(1)) + '" height="' + (rowH - 8) + '" rx="3.5" fill="url(#' + gradId + ')" opacity="0.92"><title>' + esc(r.label) + ': ' + esc(r.value) + '</title></rect>';
      html += '<text x="' + (barPad.left + bw + 7) + '" y="' + (y + rowH / 2 + 3.5) + '" font-size="12" font-weight="700" fill="var(--text-primary)">' + esc(r.value) + '</text>';
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
    const emptyHtml = '<div class="state-panel state-empty" role="status"><div><strong>' + esc(opts.emptyTitle || 'No data yet') + '</strong>' + (opts.emptyHint ? '<p>' + esc(opts.emptyHint) + '</p>' : '') + '</div></div>';
    if (!el || !data || !data.length) {
      el.innerHTML = emptyHtml;
      return;
    }
    const rows = data.filter(d => Number(d.value) > 0);
    const total = rows.reduce((s, r) => s + Number(r.value), 0);
    if (!total) {
      el.innerHTML = emptyHtml;
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
    el.innerHTML = '<div class="pie-wrap"><svg viewBox="0 0 ' + size + ' ' + size + '" role="img" aria-label="' + esc(opts.label || 'Chart') + '" class="chart-svg chart-pie">' + arcs + '<text x="' + cx + '" y="' + (cy + 5) + '" text-anchor="middle" font-size="15" font-weight="700" fill="var(--text-primary)">' + esc(total) + '</text></svg><div class="chart-legend">' + legend + '</div></div>';
  }

  window.BarkCharts = { lineChart: lineChart, barChart: barChart, pieChart: pieChart, esc: esc };
})();
