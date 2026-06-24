(function () {
  function formatActivityTimestamps() {
    // The database and server expose UTC ISO timestamps. Formatting in the
    // browser makes the admin feed reflect the viewer's local timezone without
    // changing or guessing the timezone of the stored audit data.
    document.querySelectorAll('[data-utc-timestamp]').forEach((element) => {
      const value = element.dataset.utcTimestamp;
      if (!value) return;

      const timestamp = new Date(value);
      if (Number.isNaN(timestamp.getTime())) {
        // Keep the server-rendered ISO value visible if malformed historical
        // data cannot be parsed instead of replacing it with a misleading date.
        return;
      }

      element.textContent = timestamp.toLocaleString([], {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      });
      element.title = value;
    });
  }

  document.addEventListener('DOMContentLoaded', formatActivityTimestamps);
})();
