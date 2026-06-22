(function () {
  const SVG_NS = 'http://www.w3.org/2000/svg';

  function polarToCartesian(cx, cy, r, angleDeg) {
    const angleRad = angleDeg * Math.PI / 180;
    return {
      x: cx + r * Math.cos(angleRad),
      y: cy + r * Math.sin(angleRad),
    };
  }

  function describeArc(cx, cy, r, startValue, endValue) {
    const startAngle = valueToAngle(startValue);
    const endAngle = valueToAngle(endValue);
    const start = polarToCartesian(cx, cy, r, startAngle);
    const end = polarToCartesian(cx, cy, r, endAngle);
    const largeArcFlag = Math.abs(endAngle - startAngle) <= 180 ? '0' : '1';
    return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
  }

  function valueToAngle(value) {
    return 180 + (value / 100) * 180;
  }

  function pointForValue(cx, cy, r, value) {
    return polarToCartesian(cx, cy, r, valueToAngle(value));
  }

  function clampValue(value) {
    return Math.max(0, Math.min(100, Number(value)));
  }

  function createSvgElement(name, attrs = {}) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attrs)) {
      node.setAttribute(key, value);
    }
    return node;
  }

  function makeDial(container, options = {}) {
    const state = {
      value: Number(container.dataset.value || 50),
      readOnly: Boolean(options.readOnly),
      onChange: options.onChange || function () {},
    };

    container.innerHTML = '';
    const svg = createSvgElement('svg', { viewBox: '0 0 360 196', role: 'img', 'aria-label': 'Wavelength dial' });
    const cx = 180;
    const cy = 178;
    const r = 145;

    const arcBg = createSvgElement('path', { d: describeArc(cx, cy, r, 0, 100), class: 'arc-bg' });
    svg.appendChild(arcBg);

    if (options.showBands) {
      // Bands are opt-in because live Guesser and Cluer dials do not have
      // completed answer distributions yet. History graphics can still request
      // colored scoring bands when they need to show how a score was earned.
      const zones = [
        [32.5, 42.5, 'arc-zone-1'],
        [42.5, 57.5, 'arc-zone-2'],
        [57.5, 67.5, 'arc-zone-3'],
      ];
      for (const [start, end, className] of zones) {
        svg.appendChild(createSvgElement('path', { d: describeArc(cx, cy, r, start, end), class: className }));
      }
    }

    let targetMarker = null;
    if (options.showTarget) {
      targetMarker = createSvgElement('line', { class: 'target-marker' });
      svg.appendChild(targetMarker);
    }

    const needle = createSvgElement('line', { class: 'needle', x1: cx, y1: cy });
    const knob = createSvgElement('circle', { class: 'knob', cx, cy, r: 9 });
    svg.appendChild(needle);
    svg.appendChild(knob);
    container.appendChild(svg);

    function render() {
      const point = pointForValue(cx, cy, r - 8, state.value);
      needle.setAttribute('x2', point.x);
      needle.setAttribute('y2', point.y);
      container.dataset.value = state.value.toFixed(2);

      if (targetMarker) {
        const outer = pointForValue(cx, cy, r + 22, state.value);
        const inner = pointForValue(cx, cy, r - 26, state.value);
        targetMarker.setAttribute('x1', inner.x);
        targetMarker.setAttribute('y1', inner.y);
        targetMarker.setAttribute('x2', outer.x);
        targetMarker.setAttribute('y2', outer.y);
      }
    }

    function commitValue(value) {
      // Centralizing value updates keeps clicks, drags, and programmatic
      // resets clamped to the same 0-100 dial range and guarantees every visible
      // needle move also notifies the owning screen.
      state.value = clampValue(value);
      render();
      state.onChange(state.value);
    }

    function setFromPointer(event) {
      if (state.readOnly) return;
      const rect = svg.getBoundingClientRect();
      const scaleX = 360 / rect.width;
      const scaleY = 196 / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      const dx = x - cx;
      const dy = y - cy;
      let angle = Math.atan2(dy, dx) * 180 / Math.PI;
      if (angle < 0) {
        angle += 360;
      }

      // The interactive range is the top half of the dial: 180 degrees on the
      // left, 270 degrees at the top, and 360/0 degrees on the right. Pointer
      // events below the dial are clamped to the closest side so clicks and
      // drags feel like a physical semicircular control.
      if (angle < 180) {
        angle = x < cx ? 180 : 360;
      }
      const value = Math.max(0, Math.min(100, ((angle - 180) / 180) * 100));
      commitValue(value);
    }

    let activePointerId = null;
    if (!state.readOnly) {
      container.style.cursor = 'grab';
      svg.addEventListener('pointerdown', (event) => {
        if (state.readOnly) return;
        activePointerId = event.pointerId;
        svg.setPointerCapture?.(event.pointerId);
        container.style.cursor = 'grabbing';
        setFromPointer(event);
        event.preventDefault();
      });
      svg.addEventListener('pointermove', (event) => {
        if (activePointerId !== event.pointerId) return;
        setFromPointer(event);
        event.preventDefault();
      });
      window.addEventListener('pointerup', (event) => {
        if (activePointerId !== event.pointerId) return;
        activePointerId = null;
        container.style.cursor = 'grab';
      });
      window.addEventListener('pointercancel', (event) => {
        if (activePointerId !== event.pointerId) return;
        activePointerId = null;
        container.style.cursor = 'grab';
      });
    }

    render();

    return {
      getValue() {
        return state.value;
      },
      setValue(value) {
        commitValue(value);
      },
      disable() {
        state.readOnly = true;
        container.style.cursor = 'default';
      },
      enable() {
        state.readOnly = false;
        container.style.cursor = 'grab';
      },
    };
  }

  window.WavelengthDial = { makeDial };
})();
