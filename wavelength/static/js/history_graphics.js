(function () {
  // The compact history arcs use their own SVG geometry so table rows stay
  // small while still matching the live dial's 0-100 left-to-right scale.
  const HISTORY_ARC = {
    width: 220,
    height: 124,
    cx: 110,
    cy: 104,
    radius: 84,
  };

  // History scoring bands intentionally mirror the requested visual language:
  // one centered blue 4-point band, two orange 3-point bands, and two yellow
  // 2-point bands. The bands are clipped to the 0-100 dial range per row.
  const HISTORY_BAND_SEGMENTS = [
    [-12.5, -7.5, 'history-band-2'],
    [-7.5, -2.5, 'history-band-3'],
    [-2.5, 2.5, 'history-band-4'],
    [2.5, 7.5, 'history-band-3'],
    [7.5, 12.5, 'history-band-2'],
  ];

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function normalizedDialValue(value) {
    // API rows can legitimately have no current average yet. Returning null for
    // non-numeric values lets the SVG renderer omit only the missing marker or
    // band while still drawing the rest of the row's available information.
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    return Math.max(0, Math.min(100, number));
  }

  function historyValueToAngle(value) {
    return 180 + (value / 100) * 180;
  }

  function historyPointForValue(radius, value) {
    const angleRad = historyValueToAngle(value) * Math.PI / 180;
    return {
      x: HISTORY_ARC.cx + radius * Math.cos(angleRad),
      y: HISTORY_ARC.cy + radius * Math.sin(angleRad),
    };
  }

  function historyArcPath(startValue, endValue) {
    // Every mini-arc path is built from dial values rather than pixel offsets so
    // clipped bands near 0 or 100 still stay attached to the correct part of the
    // semicircle.
    const start = historyPointForValue(HISTORY_ARC.radius, startValue);
    const end = historyPointForValue(HISTORY_ARC.radius, endValue);
    const largeArcFlag = Math.abs(historyValueToAngle(endValue) - historyValueToAngle(startValue)) <= 180 ? '0' : '1';
    return `M ${start.x} ${start.y} A ${HISTORY_ARC.radius} ${HISTORY_ARC.radius} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
  }

  function renderHistoryBands(centerValue) {
    // A row's scoring bands are centered on the reference answer that the caller
    // wants players to compare against, such as a global average or target.
    const center = normalizedDialValue(centerValue);
    if (center === null) return '';
    return HISTORY_BAND_SEGMENTS.map(([startOffset, endOffset, className]) => {
      const start = normalizedDialValue(center + startOffset);
      const end = normalizedDialValue(center + endOffset);
      if (start === null || end === null || end <= start) return '';
      return `<path class="${className}" d="${historyArcPath(start, end)}"></path>`;
    }).join('');
  }

  function renderHistoryMarker(value, className) {
    // Markers are radial pins, matching the main dial metaphor while avoiding
    // visible numbers. Different classes supply the meaning for each view.
    const normalized = normalizedDialValue(value);
    if (normalized === null) return '';
    const outer = historyPointForValue(HISTORY_ARC.radius - 5, normalized);
    return `<line class="history-marker ${className}" x1="${HISTORY_ARC.cx}" y1="${HISTORY_ARC.cy}" x2="${outer.x}" y2="${outer.y}"></line>`;
  }

  function renderHistoryArc({ bandCenter, markers, ariaLabel }) {
    // This generator returns a complete inline SVG so each table can draw the
    // exact marker combination it needs while sharing one band renderer.
    return `
      <svg class="history-arc" viewBox="0 0 ${HISTORY_ARC.width} ${HISTORY_ARC.height}" role="img" aria-label="${escapeHtml(ariaLabel)}">
        <path class="history-arc-bg" d="${historyArcPath(0, 100)}"></path>
        ${renderHistoryBands(bandCenter)}
        ${markers.map(marker => renderHistoryMarker(marker.value, marker.className)).join('')}
      </svg>`;
  }

  window.WavelengthHistoryGraphics = {
    renderHistoryArc,
  };
})();
