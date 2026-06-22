(function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

  const state = {
    guesser: null,
    cluer: null,
    guessDial: null,
    targetDial: null,
    // The Guesser panel is a two-step flow backed by one dial. `guessStep`
    // decides whether the current dial value should be treated as the player's
    // personal opinion or as their prediction of the eventual global average.
    guessStep: 'personal',
    // Stores the first-step opinion while the player is on the second step.
    // This lets the same visible dial stay in place for the global-average
    // prediction, which makes "same as my opinion" a one-click action.
    personalPosition: null,
  };

  const $ = (id) => document.getElementById(id);

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

  function setStatus(message) {
    $('globalStatus').textContent = message || '';
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
        ...(options.headers || {}),
      },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.message || data.error || 'Request failed');
      error.data = data;
      throw error;
    }
    return data;
  }

  function scoreHtml(payload) {
    if (payload.score_status === 'pending') {
      return `<strong>Pending</strong><br>${payload.message || `Needs more guesses. Current guesses: ${payload.guess_count}`}`;
    }
    return [
      `<strong>${payload.score} / 4 points</strong>`,
      `Global average: ${payload.global_average}`,
      `Distance: ${payload.distance}`,
      `Total guesses: ${payload.guess_count}`,
    ].join('<br>');
  }

  function setGuesserPlayingMode() {
    $('guessDialStage').classList.remove('hidden');
    $('submitGuessBtn').classList.remove('hidden');
    $('guessResult').classList.add('hidden');
    $('guessResult').innerHTML = '';
  }

  function renderGuessSubmissionGraphic(personalPosition, predictedAverage, globalAverage) {
    return renderGuessHistoryGraphic({
      personal_position: personalPosition,
      predicted_average_position: predictedAverage,
      current_global_average: globalAverage,
    });
  }

  function showGuesserResult(data) {
    const personalPosition = state.personalPosition;
    const predictedAverage = state.guessDial.getValue();

    $('guessDialStage').classList.add('hidden');
    $('submitGuessBtn').classList.add('hidden');

    const result = $('guessResult');
    result.classList.remove('hidden');

    if (data.score_status === 'pending') {
      result.innerHTML = `
        <div class="guess-result-pending">
          <strong>Score pending</strong>
          <p>${escapeHtml(data.message || `This clue needs more guesses before it can be scored.`)}</p>
          <p class="muted">${data.guess_count} guess${data.guess_count === 1 ? '' : 'es'} so far on this clue.</p>
        </div>
        <button id="guessResultPlayAnotherBtn" type="button" class="guess-result-next">Play another</button>
      `;
    } else {
      result.innerHTML = `
        <div class="guess-result-score">${data.score} / 4 points</div>
        <div class="guess-result-arc">${renderGuessSubmissionGraphic(personalPosition, predictedAverage, data.global_average)}</div>
        <p class="guess-result-meta">N = ${data.guess_count}</p>
        <button id="guessResultPlayAnotherBtn" type="button" class="guess-result-next">Play another</button>
      `;
    }

    $('guessResultPlayAnotherBtn').addEventListener('click', loadGuesserPrompt);
  }

  function showResult(elementId, html, kind = 'success') {
    const element = $(elementId);
    element.innerHTML = html;
    element.classList.remove('hidden', 'success', 'error');
    element.classList.add(kind);
  }

  function formatDate(value) {
    if (!value) return '';
    try {
      return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    } catch {
      return value;
    }
  }

  function renderGuesser(prompt) {
    state.guesser = prompt;
    state.guessStep = 'personal';
    state.personalPosition = null;
    setGuesserPlayingMode();
    $('submitGuessBtn').disabled = false;
    $('submitGuessBtn').textContent = 'Submit Opinion';

    if (!prompt) {
      $('guesserEmpty').classList.remove('hidden');
      $('guesserContent').classList.add('hidden');
      return;
    }

    $('guesserEmpty').classList.add('hidden');
    $('guesserContent').classList.remove('hidden');
    $('guesserLeft').textContent = prompt.spectrum.left_label;
    $('guesserRight').textContent = prompt.spectrum.right_label;
    $('guesserClue').textContent = prompt.clue_text;

    $('guessDialTitle').textContent = "What's your personal opinion (not scored yet!)";
    state.guessDial.setValue(50);
    state.guessDial.enable();
  }

  function renderCluer(prompt) {
    state.cluer = prompt;
    $('clueResult').classList.add('hidden');
    $('submitClueBtn').disabled = false;
    $('clueInput').disabled = false;
    $('clueInput').value = '';

    if (!prompt) {
      $('cluerEmpty').classList.remove('hidden');
      $('cluerContent').classList.add('hidden');
      return;
    }

    $('cluerEmpty').classList.add('hidden');
    $('cluerContent').classList.remove('hidden');
    $('cluerLeft').textContent = prompt.spectrum.left_label;
    $('cluerRight').textContent = prompt.spectrum.right_label;
    state.targetDial.setValue(prompt.target_position);
  }

  async function loadPrompts() {
    setStatus('Loading prompts…');
    try {
      const data = await apiFetch('/api/prompts');
      renderGuesser(data.guesser);
      renderCluer(data.cluer);
      setStatus('');
    } catch (error) {
      setStatus('Could not load prompts. Refresh and try again.');
    }
  }

  async function loadGuesserPrompt() {
    // Refresh only the Guesser prompt so someone can skip a clue without losing
    // the current Cluer target or any clue text they may have started typing.
    setStatus('Loading guesser prompt…');
    try {
      const data = await apiFetch('/api/prompts?section=guesser');
      renderGuesser(data.guesser);
      setStatus('');
    } catch (error) {
      setStatus('Could not load a guesser prompt. Try again.');
    }
  }

  async function loadCluerPrompt() {
    // Refresh only the Cluer task so asking for another target does not disturb
    // the Guesser panel or reset a guess already in progress.
    setStatus('Loading cluer prompt…');
    try {
      const data = await apiFetch('/api/prompts?section=cluer');
      renderCluer(data.cluer);
      setStatus('');
    } catch (error) {
      setStatus('Could not load a cluer prompt. Try again.');
    }
  }

  async function refreshCluerAfterSuccessfulSubmission() {
    // Once the server accepts a clue, that exact Cluer task is spent. This helper
    // immediately requests the next target so the player can keep cluing without
    // clicking Play another, while refreshing leaderboards/history/stats in
    // parallel because those panels are useful but not required for the next turn.
    const [nextPromptResult, leaderboardsResult, historyResult, statsResult] = await Promise.allSettled([
      apiFetch('/api/prompts?section=cluer'),
      loadLeaderboards(),
      loadHistory(),
      loadStats(),
    ]);

    if (nextPromptResult.status === 'fulfilled') {
      renderCluer(nextPromptResult.value.cluer);
    } else {
      // The clue was already submitted successfully, so a follow-up prompt failure
      // should leave the used task locked and tell the player exactly what still
      // needs retrying instead of making the submission look like it failed.
      $('submitClueBtn').disabled = true;
      $('clueInput').disabled = true;
      showResult('clueResult', 'Clue submitted, but the next cluer prompt could not load. Click Play another to try again.', 'error');
    }

    if (
      leaderboardsResult.status === 'rejected'
      || historyResult.status === 'rejected'
      || statsResult.status === 'rejected'
    ) {
      setStatus('Clue submitted. Some score panels may need a refresh.');
      return;
    }

    setStatus('');
  }

  async function submitGuess() {
    if (!state.guesser) return;

    // The guess flow intentionally uses one physical dial for two answers. The
    // first click stores the player's own opinion, then the same dial remains
    // exactly where it was so matching the average-opinion guess is a single
    // extra submit instead of a second adjustment.
    if (state.guessStep === 'personal') {
      state.personalPosition = state.guessDial.getValue();
      state.guessStep = 'prediction';
      $('guessDialTitle').textContent = "What do you think the average opinion will be among everyone? (this is what you're scored on as a guesser)";
      $('submitGuessBtn').textContent = 'Submit Average Guess';
      return;
    }

    $('submitGuessBtn').disabled = true;
    setStatus('Submitting guess…');
    try {
      const data = await apiFetch('/api/guesses', {
        method: 'POST',
        body: JSON.stringify({
          clue_id: state.guesser.clue_id,
          personal_position: state.personalPosition,
          predicted_average_position: state.guessDial.getValue(),
        }),
      });
      state.guessDial.disable();
      showGuesserResult(data);
      await Promise.all([loadLeaderboards(), loadHistory(), loadStats()]);
      setStatus('');
    } catch (error) {
      $('submitGuessBtn').disabled = false;
      $('guessResult').classList.remove('hidden');
      $('guessResult').innerHTML = `<div class="guess-result-error">${escapeHtml(error.message)}</div>`;
      setStatus('');
    }
  }

  async function submitClue() {
    if (!state.cluer) return;
    const text = $('clueInput').value.trim();
    if (!text) {
      showResult('clueResult', 'Please enter a clue.', 'error');
      return;
    }

    $('submitClueBtn').disabled = true;
    setStatus('Submitting clue…');
    try {
      const data = await apiFetch('/api/clues', {
        method: 'POST',
        body: JSON.stringify({
          task_id: state.cluer.task_id,
          text,
        }),
      });
      $('clueInput').disabled = true;
      showResult('clueResult', data.message || 'Clue submitted. Loading the next target…', 'success');
      setStatus('Clue submitted. Loading the next target…');
      await refreshCluerAfterSuccessfulSubmission();
    } catch (error) {
      $('submitClueBtn').disabled = false;
      showResult('clueResult', error.message, 'error');
      setStatus('');
    }
  }

  function renderLeaderboard(data) {
    const rows = data.rows || [];
    if (!rows.length) {
      return `<div class="empty">No eligible ${data.role} leaderboard entries yet. Minimum scored entries: ${data.minimum_scored_entries}.</div>`;
    }
    return `
      <table>
        <thead>
          <tr>
            <th>#</th><th>User</th><th class="numeric">Avg</th><th class="numeric">Scored</th><th class="numeric">Total</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td>${row.rank}</td>
              <td>${escapeHtml(row.username)}</td>
              <td class="numeric">${row.average_score}</td>
              <td class="numeric">${row.scored_entries}</td>
              <td class="numeric">${row.total_points}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  function leaderboardTitle(role, period) {
    const roleLabel = role === 'guesser' ? 'Guesser' : 'Cluer';
    const periodLabel = period === 'daily' ? 'Daily' : 'Lifetime';
    return `${roleLabel} · ${periodLabel}`;
  }

  function renderLeaderboardStack(results) {
    $('leaderboardStack').innerHTML = results.map(({ role, period, data }) => `
      <section class="leaderboard-block">
        <h3>${leaderboardTitle(role, period)}</h3>
        ${renderLeaderboard(data)}
      </section>
    `).join('');
  }

  async function loadLeaderboards() {
    const modes = [
      { role: 'guesser', period: 'daily' },
      { role: 'guesser', period: 'lifetime' },
      { role: 'cluer', period: 'daily' },
      { role: 'cluer', period: 'lifetime' },
    ];

    // The sidebar now shows every leaderboard mode at once, but the backend
    // already exposes the exact role/period combinations we need. Fetching them
    // together keeps the UI fresh without introducing a new aggregate endpoint.
    const results = await Promise.all(modes.map(async (mode) => {
      const data = await apiFetch(`/api/leaderboards?role=${encodeURIComponent(mode.role)}&period=${encodeURIComponent(mode.period)}`);
      return { ...mode, data };
    }));
    renderLeaderboardStack(results);
  }

  function statusText(item) {
    if (item.status === 'pending') return `<span class="status-pending">Pending (${item.guess_count}/3)</span>`;
    return `<span class="status-scored">${item.score}/4</span>`;
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
    // A row's scoring bands are centered on the thing being judged: the current
    // global average for guess history and the true target for clue history.
    // Each segment is clipped independently so edge targets keep their visible
    // partial scoring bands instead of overflowing past the arc endpoints.
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
    // visible numbers. Different classes supply the requested blue, red, and
    // black meanings for personal opinion, predicted/actual average, and target.
    const normalized = normalizedDialValue(value);
    if (normalized === null) return '';
    const outer = historyPointForValue(HISTORY_ARC.radius - 5, normalized);
    return `<line class="history-marker ${className}" x1="${HISTORY_ARC.cx}" y1="${HISTORY_ARC.cy}" x2="${outer.x}" y2="${outer.y}"></line>`;
  }

  function renderHistoryArc({ bandCenter, markers, ariaLabel }) {
    // This generator returns a complete inline SVG so every history row can draw
    // exactly the combination it needs: guess rows use blue/red pins with bands
    // around the average, while clue rows use black/red pins with bands around
    // the target.
    return `
      <svg class="history-arc" viewBox="0 0 ${HISTORY_ARC.width} ${HISTORY_ARC.height}" role="img" aria-label="${escapeHtml(ariaLabel)}">
        <path class="history-arc-bg" d="${historyArcPath(0, 100)}"></path>
        ${renderHistoryBands(bandCenter)}
        ${markers.map(marker => renderHistoryMarker(marker.value, marker.className)).join('')}
      </svg>`;
  }

  function renderGuessHistoryGraphic(row) {
    return renderHistoryArc({
      bandCenter: row.current_global_average,
      ariaLabel: 'Blue pin shows your personal opinion. Red pin shows your guess for the average opinion.',
      markers: [
        { value: row.personal_position, className: 'history-marker-personal' },
        { value: row.predicted_average_position, className: 'history-marker-average' },
      ],
    });
  }

  function renderClueHistoryGraphic(row) {
    // Clue history compares two different meanings on the same dial: the target
    // the cluer was asked to hit and the current global average produced by the
    // guessers. The legend makes that distinction visible without forcing players
    // to infer it from marker color alone.
    return `
      ${renderHistoryArc({
        bandCenter: row.target_position,
        ariaLabel: 'Black pin shows the true target. Red pin shows the current global average opinion.',
        markers: [
          { value: row.target_position, className: 'history-marker-target' },
          { value: row.current_global_average, className: 'history-marker-average' },
        ],
      })}
      <div class="history-legend" aria-hidden="true">
        <span><span class="history-legend-swatch history-legend-target"></span>Your target</span>
        <span><span class="history-legend-swatch history-legend-average"></span>Global average</span>
      </div>`;
  }

  function renderClueHistoryResult(row) {
    // Clue scoring bands only make sense after enough people have guessed and a
    // global average exists. While a clue is pending, hide the dial entirely so
    // players do not see bands that imply a score has already been calculated.
    if (row.status === 'pending') {
      return `<div class="history-pending-note">Waiting for more guesses before showing the target comparison.</div>`;
    }

    return renderClueHistoryGraphic(row);
  }

  function historyExplanation(kind) {
    // The history tabs are rendered from JavaScript because the rows are fetched
    // asynchronously. Keeping each scoring explanation with its table ensures the
    // right description appears whenever the active tab is populated or refreshed.
    if (kind === 'guesses') {
      return '<p class="history-description muted">Past guesses score higher when your average-opinion guess lands closer to the global average opinion for that clue.</p>';
    }

    return "<p class=\"history-description muted\">Past clues score higher when the global average of other people's guesses lands closer to the target you were given for your clue.</p>";
  }

  function renderHistoryTable(kind, tableHtml) {
    return `
      ${historyExplanation(kind)}
      ${tableHtml}`;
  }

  function emptyHistory(kind, message) {
    return renderHistoryTable(kind, `<div class="empty">${message}</div>`);
  }

  function renderGuessHistory(rows) {
    if (!rows.length) {
      $('historyGuesses').innerHTML = emptyHistory('guesses', 'No guesses yet.');
      return;
    }
    $('historyGuesses').innerHTML = renderHistoryTable('guesses', `
      <table>
        <thead><tr>
          <th>Date</th><th>Spectrum</th><th>Clue</th><th>Result</th><th class="numeric">Points</th>
        </tr></thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td>${formatDate(row.created_at)}</td>
              <td>${escapeHtml(row.spectrum)}</td>
              <td>${escapeHtml(row.clue_text)}</td>
              <td class="history-arc-cell">${renderGuessHistoryGraphic(row)}</td>
              <td class="numeric">${statusText(row)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`);
  }

  function renderClueHistory(rows) {
    if (!rows.length) {
      $('historyClues').innerHTML = emptyHistory('clues', 'No clues yet.');
      return;
    }
    $('historyClues').innerHTML = renderHistoryTable('clues', `
      <table>
        <thead><tr>
          <th>Date</th><th>Spectrum</th><th>Clue</th><th>Result</th><th class="numeric">Points</th>
        </tr></thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td>${formatDate(row.created_at)}</td>
              <td>${escapeHtml(row.spectrum)}</td>
              <td>${escapeHtml(row.clue_text)}</td>
              <td class="history-arc-cell">${renderClueHistoryResult(row)}</td>
              <td class="numeric">${statusText(row)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`);
  }

  async function loadHistory() {
    const data = await apiFetch('/api/me/history');
    renderGuessHistory(data.guesses || []);
    renderClueHistory(data.clues || []);
  }

  async function loadStats() {
    const stats = await apiFetch('/api/stats');
    $('siteStats').textContent = `${stats.users} users · ${stats.clues} clues · ${stats.guesses} guesses · scores need ${stats.min_guesses_for_score} guesses`;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function setupTabs() {
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.dataset.tab;
        $('historyGuesses').classList.toggle('hidden', target !== 'guesses');
        $('historyClues').classList.toggle('hidden', target !== 'clues');
      });
    });
  }

  function initializeDials() {
    state.guessDial = window.WavelengthDial.makeDial($('guessDial'));
    state.targetDial = window.WavelengthDial.makeDial($('targetDial'), {
      readOnly: true,
      showTarget: true,
    });
  }

  function bindEvents() {
    $('playAnotherGuesserBtn').addEventListener('click', loadGuesserPrompt);
    $('playAnotherCluerBtn').addEventListener('click', loadCluerPrompt);
    $('submitGuessBtn').addEventListener('click', submitGuess);
    $('submitClueBtn').addEventListener('click', submitClue);
    $('refreshHistoryBtn').addEventListener('click', loadHistory);
  }

  document.addEventListener('DOMContentLoaded', async () => {
    initializeDials();
    setupTabs();
    bindEvents();
    await Promise.all([loadPrompts(), loadLeaderboards(), loadHistory(), loadStats()]);
  });
})();
