(function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

  const state = {
    friends: [],
    selectedFriendId: null,
    comparison: null,
    activeTab: 'guesses',
  };

  const $ = (id) => document.getElementById(id);

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

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function formatDate(value) {
    if (!value) return '';
    try {
      return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    } catch {
      return value;
    }
  }

  function setRequestStatus(message, kind = '') {
    const element = $('friendRequestStatus');
    element.textContent = message || '';
    element.classList.remove('success', 'error');
    if (kind) element.classList.add(kind);
  }

  function emptyBlock(message) {
    return `<div class="empty">${escapeHtml(message)}</div>`;
  }

  function renderRequestList(requests, kind) {
    if (!requests.length) {
      return emptyBlock(kind === 'incoming' ? 'No incoming requests.' : 'No outgoing requests.');
    }

    return requests.map((request) => {
      // Incoming requests expose a choice because the current player owns the
      // decision; outgoing requests only expose cancel because the friend has to
      // accept before the relationship exists.
      const actions = kind === 'incoming'
        ? `
          <button type="button" class="mini-button" data-request-action="accept" data-request-id="${request.id}">Accept</button>
          <button type="button" class="mini-button secondary" data-request-action="decline" data-request-id="${request.id}">Decline</button>
        `
        : `<button type="button" class="mini-button secondary" data-request-action="cancel" data-request-id="${request.id}">Cancel</button>`;

      return `
        <div class="friend-request-card">
          <div>
            <strong>${escapeHtml(request.username)}</strong>
            <div class="muted">${formatDate(request.created_at)}</div>
          </div>
          <div class="friend-request-actions">${actions}</div>
        </div>`;
    }).join('');
  }

  function renderFriendsList() {
    if (!state.friends.length) {
      $('friendsList').innerHTML = emptyBlock('No friends yet.');
      return;
    }

    $('friendsList').innerHTML = state.friends.map((friend) => `
      <button
        type="button"
        class="friend-list-button${friend.id === state.selectedFriendId ? ' active' : ''}"
        data-friend-id="${friend.id}"
      >${escapeHtml(friend.username)}</button>
    `).join('');
  }

  function renderSidebar(data) {
    state.friends = data.friends || [];
    $('incomingRequests').innerHTML = renderRequestList(data.incoming_requests || [], 'incoming');
    $('outgoingRequests').innerHTML = renderRequestList(data.outgoing_requests || [], 'outgoing');
    renderFriendsList();
  }

  function friendById(friendId) {
    return state.friends.find((friend) => friend.id === friendId) || null;
  }

  function renderLegend(items) {
    // The friends page uses the same small legend pattern as history rows, but
    // each tab has different marker meanings so the labels are passed in here.
    return `
      <div class="history-legend friend-comparison-legend" aria-hidden="true">
        ${items.map(item => `
          <span><span class="history-legend-swatch ${item.className}"></span>${escapeHtml(item.label)}</span>
        `).join('')}
        <span><span class="history-legend-band"></span>Global average bands</span>
      </div>`;
  }

  function renderGuessComparisonGraphic(row) {
    return `
      ${window.WavelengthHistoryGraphics.renderHistoryArc({
        bandCenter: row.current_global_average,
        ariaLabel: 'Blue pin shows your guess. Purple pin shows your friend guess. Bands are centered on the global average.',
        markers: [
          { value: row.your_predicted_average_position, className: 'history-marker-you' },
          { value: row.friend_predicted_average_position, className: 'history-marker-friend' },
        ],
      })}
      ${renderLegend([
        { className: 'history-legend-you', label: 'Your guess' },
        { className: 'history-legend-friend', label: 'Friend guess' },
      ])}`;
  }

  function renderClueComparisonGraphic(row) {
    return `
      ${window.WavelengthHistoryGraphics.renderHistoryArc({
        bandCenter: row.current_global_average,
        ariaLabel: 'Black pin shows friend target. Blue pin shows your guess. Bands are centered on the global average.',
        markers: [
          { value: row.friend_target_position, className: 'history-marker-target' },
          { value: row.your_predicted_average_position, className: 'history-marker-you' },
        ],
      })}
      ${renderLegend([
        { className: 'history-legend-target', label: 'Friend target' },
        { className: 'history-legend-you', label: 'Your guess' },
      ])}`;
  }

  function renderGuesses(rows) {
    if (!rows.length) {
      $('friendGuesses').innerHTML = emptyBlock('No shared answered clues yet.');
      return;
    }

    $('friendGuesses').innerHTML = `
      <p class="history-description muted">Shared guesses compare each player&apos;s scored prediction for clues both of you answered.</p>
      <table>
        <thead><tr>
          <th>Date</th><th>Spectrum</th><th>Clue</th><th>Comparison</th><th class="numeric">N</th>
        </tr></thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td>${formatDate(row.created_at)}</td>
              <td>${escapeHtml(row.spectrum)}</td>
              <td>${escapeHtml(row.clue_text)}</td>
              <td class="history-arc-cell">${renderGuessComparisonGraphic(row)}</td>
              <td class="numeric">${row.guess_count}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  function renderClues(rows) {
    if (!rows.length) {
      $('friendClues').innerHTML = emptyBlock('No friend clues answered by you yet.');
      return;
    }

    $('friendClues').innerHTML = `
      <p class="history-description muted">Friend clues show clues your friend wrote that you answered, with your scored prediction shown against their target and the current global average bands.</p>
      <table>
        <thead><tr>
          <th>Date</th><th>Spectrum</th><th>Clue</th><th>Comparison</th><th class="numeric">N</th>
        </tr></thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td>${formatDate(row.created_at)}</td>
              <td>${escapeHtml(row.spectrum)}</td>
              <td>${escapeHtml(row.clue_text)}</td>
              <td class="history-arc-cell">${renderClueComparisonGraphic(row)}</td>
              <td class="numeric">${row.guess_count}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  function renderComparison() {
    if (!state.selectedFriendId || !state.comparison) {
      $('friendComparisonEmpty').classList.remove('hidden');
      $('friendComparisonContent').classList.add('hidden');
      $('selectedFriendTitle').textContent = 'Select a friend';
      $('selectedFriendSubtitle').textContent = 'Choose a friend from the sidebar to compare answers.';
      return;
    }

    const friend = state.comparison.friend || friendById(state.selectedFriendId);
    $('friendComparisonEmpty').classList.add('hidden');
    $('friendComparisonContent').classList.remove('hidden');
    $('selectedFriendTitle').textContent = friend ? friend.username : 'Friend comparison';
    $('selectedFriendSubtitle').textContent = 'Compare scored guesses and answered clues.';
    renderGuesses(state.comparison.guesses || []);
    renderClues(state.comparison.clues || []);
    setActiveTab(state.activeTab);
  }

  function setActiveTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll('[data-friend-tab]').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.friendTab === tabName);
    });
    $('friendGuesses').classList.toggle('hidden', tabName !== 'guesses');
    $('friendClues').classList.toggle('hidden', tabName !== 'clues');
  }

  async function loadFriends() {
    const data = await apiFetch('/api/friends');
    renderSidebar(data);

    // If the selected friend disappeared because the relationship changed, clear
    // the main panel instead of leaving stale comparison rows on screen.
    if (state.selectedFriendId && !friendById(state.selectedFriendId)) {
      state.selectedFriendId = null;
      state.comparison = null;
      renderComparison();
    }
  }

  async function loadComparison(friendId) {
    state.selectedFriendId = friendId;
    state.comparison = null;
    renderFriendsList();
    $('friendComparisonEmpty').classList.remove('hidden');
    $('friendComparisonEmpty').textContent = 'Loading comparison...';
    $('friendComparisonContent').classList.add('hidden');

    try {
      state.comparison = await apiFetch(`/api/friends/${encodeURIComponent(friendId)}/comparison`);
      $('friendComparisonEmpty').textContent = 'No friend selected.';
      renderComparison();
    } catch (error) {
      $('friendComparisonEmpty').textContent = error.message;
    }
  }

  async function submitFriendRequest(event) {
    event.preventDefault();
    const input = $('friendUsername');
    const username = input.value.trim();
    setRequestStatus('Sending...');

    try {
      await apiFetch('/api/friend-requests', {
        method: 'POST',
        body: JSON.stringify({ username }),
      });
      input.value = '';
      setRequestStatus('Friend request sent.', 'success');
      await loadFriends();
    } catch (error) {
      setRequestStatus(error.message, 'error');
    }
  }

  async function handleRequestAction(action, requestId) {
    // The action name is intentionally constrained by the buttons we render, so
    // arbitrary DOM changes cannot send unexpected request verbs to the API.
    if (!['accept', 'decline', 'cancel'].includes(action)) return;

    setRequestStatus('');
    await apiFetch(`/api/friend-requests/${encodeURIComponent(requestId)}/${action}`, { method: 'POST' });
    await loadFriends();
    if (state.selectedFriendId) await loadComparison(state.selectedFriendId);
  }

  function bindEvents() {
    $('friendRequestForm').addEventListener('submit', submitFriendRequest);
    $('refreshFriendsBtn').addEventListener('click', async () => {
      await loadFriends();
      if (state.selectedFriendId) await loadComparison(state.selectedFriendId);
    });

    document.addEventListener('click', async (event) => {
      const friendButton = event.target.closest('[data-friend-id]');
      if (friendButton) {
        await loadComparison(Number(friendButton.dataset.friendId));
        return;
      }

      const requestButton = event.target.closest('[data-request-action]');
      if (requestButton) {
        try {
          await handleRequestAction(requestButton.dataset.requestAction, requestButton.dataset.requestId);
        } catch (error) {
          setRequestStatus(error.message, 'error');
        }
      }
    });

    document.querySelectorAll('[data-friend-tab]').forEach((tab) => {
      tab.addEventListener('click', () => setActiveTab(tab.dataset.friendTab));
    });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    bindEvents();
    await loadFriends();
    renderComparison();
  });
})();
