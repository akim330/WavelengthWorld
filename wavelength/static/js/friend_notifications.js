(function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  let lastIncomingCount = Number(sessionStorage.getItem('lastIncomingFriendRequestCount') || 0);
  let toastTimer = null;

  async function fetchIncomingCount() {
    const response = await fetch('/api/friends', {
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
    });
    if (!response.ok) return null;
    const data = await response.json().catch(() => null);
    return data ? (data.incoming_requests || []).length : null;
  }

  function ensureToast() {
    let toast = document.getElementById('friendRequestToast');
    if (toast) return toast;

    toast = document.createElement('div');
    toast.id = 'friendRequestToast';
    toast.className = 'friend-request-toast hidden';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.appendChild(toast);
    return toast;
  }

  function showFriendRequestToast(count) {
    // The notification is intentionally lightweight and in-app: friend requests
    // are social state, so the player should see them without granting browser
    // notification permissions or leaving their current game flow.
    if (count <= 0) return;
    const toast = ensureToast();
    toast.innerHTML = `
      <strong>${count === 1 ? 'New friend request' : `${count} friend requests`}</strong>
      <a href="/friends">Review</a>
      <button type="button" aria-label="Dismiss friend request notification">&times;</button>
    `;
    toast.classList.remove('hidden');
    toast.querySelector('button').addEventListener('click', () => toast.classList.add('hidden'), { once: true });

    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.add('hidden'), 9000);
  }

  function updateFriendNavBadge(count) {
    // The top-nav badge is the persistent notification surface: unlike the
    // temporary toast, it stays visible until the incoming request count is zero.
    document.querySelectorAll('[data-friend-nav-link]').forEach((link) => {
      link.classList.toggle('has-pending', count > 0);
      if (count > 0) {
        link.setAttribute('aria-label', `Friends, ${count} pending friend ${count === 1 ? 'request' : 'requests'}`);
      } else {
        link.removeAttribute('aria-label');
      }
    });
  }

  function updateIncomingCount(count) {
    if (count === null) return;
    updateFriendNavBadge(count);
    if (count > lastIncomingCount || (count > 0 && lastIncomingCount === 0)) {
      showFriendRequestToast(count);
    }
    lastIncomingCount = count;
    sessionStorage.setItem('lastIncomingFriendRequestCount', String(count));
  }

  async function pollFriendRequests() {
    try {
      updateIncomingCount(await fetchIncomingCount());
    } catch {
      // Friend notifications are non-critical. If the request fails, the normal
      // Friends page still loads request state when the player opens it.
    }
  }

  window.WavelengthFriendNotifications = {
    updateIncomingCount,
  };

  document.addEventListener('DOMContentLoaded', () => {
    pollFriendRequests();
    window.setInterval(pollFriendRequests, 30000);
  });
})();
