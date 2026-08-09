/**
 * Bark Realtime — SSE event stream for live dashboard updates.
 *
 * Connects EventSource to /api/v1/guilds/{id}/events and dispatches
 * events to registered handlers. Auto-reconnects with exponential backoff.
 * Shows toast notifications for important events.
 *
 * Dependencies: main.js (showToast), lucide (icons)
 */

(function () {
  "use strict";

  // ── Configuration ────────────────────────────────────

  const RECONNECT_BASE_MS = 1000; // 1 second initial backoff
  const RECONNECT_MAX_MS = 30000; // 30 second max backoff
  const GUILD_PATH_RE = /^\/guild\/(\d+)/;

  // ── State ────────────────────────────────────────────

  let eventSource = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let shouldReconnect = true;
  let guildId = null;

  // ── Handlers registry ────────────────────────────────

  const handlers = {};

  /**
   * Register a handler for an SSE event type.
   * @param {string} eventType - The SSE event name
   * @param {function} fn - Handler receiving the parsed data object
   */
  function on(eventType, fn) {
    if (!handlers[eventType]) handlers[eventType] = [];
    handlers[eventType].push(fn);
  }

  // ── Toast helpers ────────────────────────────────────

  function showToast(message, type) {
    // Use showToast from main.js if available, otherwise fallback
    if (typeof window.showToast === "function") {
      window.showToast(message, type);
    }
  }

  // ── Default handlers ─────────────────────────────────

  on("new_moderation_case", function (data) {
    const msg = `${data.action_type} case #${data.case_id} — ${data.target_tag}`;
    showToast(msg, "warning");
    // Dispatch a custom DOM event for other handlers to listen
    document.dispatchEvent(
      new CustomEvent("bark:moderation_case", { detail: data }),
    );
  });

  on("member_joined", function (data) {
    const msg = `${data.display_name || data.tag} joined the server`;
    showToast(msg, "success");
    document.dispatchEvent(
      new CustomEvent("bark:member_joined", { detail: data }),
    );
  });

  on("automod_triggered", function (data) {
    const msg = `🚨 AutoMod: ${data.rule} — ${data.user_tag} (${data.action})`;
    showToast(msg, "error");
    document.dispatchEvent(
      new CustomEvent("bark:automod_triggered", { detail: data }),
    );
  });

  on("ticket_created", function (data) {
    const msg = `Ticket opened: ${data.channel_name} by ${data.creator_tag}`;
    showToast(msg, "success");
    document.dispatchEvent(
      new CustomEvent("bark:ticket_created", { detail: data }),
    );
  });

  on("level_up", function (data) {
    const msg = `${data.tag} reached level ${data.level}!`;
    showToast(msg, "success");
    document.dispatchEvent(
      new CustomEvent("bark:level_up", { detail: data }),
    );
  });

  // ── Connection management ────────────────────────────

  function connect(gid) {
    if (!gid) return;
    if (eventSource) disconnect();

    guildId = gid;
    shouldReconnect = true;
    reconnectAttempt = 0;
    doConnect();
  }

  function doConnect() {
    if (!guildId || !shouldReconnect) return;

    const url = `/api/v1/guilds/${guildId}/events`;
    // withCredentials ensures the session cookie is sent even if the page is
    // ever served under a different origin scheme; harmless same-origin.
    eventSource = new EventSource(url, { withCredentials: true });

    eventSource.onopen = function () {
      reconnectAttempt = 0; // Reset backoff on successful connection
    };

    // Messages without an explicit event type
    eventSource.onmessage = function (e) {
      // Ignore heartbeat comments — they have no data
    };

    // Register handlers for each event type — EventSource fires
    // a named event for `event:` lines in the SSE stream.
    Object.keys(handlers).forEach(function (eventType) {
      eventSource.addEventListener(eventType, function (e) {
        try {
          const data = JSON.parse(e.data);
          // Dispatch to all registered handlers
          (handlers[eventType] || []).forEach(function (fn) {
            try {
              fn(data);
            } catch (err) {
              console.error(
                "[Bark Realtime] Handler error for",
                eventType,
                err,
              );
            }
          });
        } catch (err) {
          console.error("[Bark Realtime] Parse error:", e.data, err);
        }
      });
    });

    eventSource.onerror = function () {
      // Clean up the dead connection
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (!shouldReconnect) return;

      // EventSource cannot surface HTTP status codes. A 401 from the SSE
      // endpoint means the session expired or was never established — the
      // browser will happily retry forever. Detect auth loss via /auth/me
      // and route to the login page instead of looping.
      fetch("/auth/me", { headers: { Accept: "application/json" } })
        .then(function (resp) {
          if (resp.status === 200) {
            return resp.json();
          }
          throw new Error("auth check failed: " + resp.status);
        })
        .then(function (body) {
          if (!body || !body.data || !body.data.authenticated) {
            // Session is gone — stop reconnecting and send to login.
            shouldReconnect = false;
            console.warn("[Bark Realtime] Session expired — redirecting to login");
            window.location.href = "/auth/login";
            return;
          }
          scheduleReconnect();
        })
        .catch(function () {
          // Transient network failure — keep the backoff retry.
          scheduleReconnect();
        });
    };
  }

  function scheduleReconnect() {
    if (!shouldReconnect) return;
    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt),
      RECONNECT_MAX_MS,
    );
    reconnectAttempt++;
    console.warn(
      `[Bark Realtime] Reconnecting in ${delay}ms (attempt ${reconnectAttempt})`,
    );
    reconnectTimer = setTimeout(doConnect, delay);
  }

  function disconnect() {
    shouldReconnect = false;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    guildId = null;
    reconnectAttempt = 0;
  }

  // ── Auto-connect from URL ────────────────────────────

  function autoConnect() {
    const match = window.location.pathname.match(GUILD_PATH_RE);
    if (match) {
      connect(match[1]);
    } else {
      // Not on a guild page — ensure we're disconnected
      disconnect();
    }
  }

  // ── Init ─────────────────────────────────────────────

  let pathWatchTimer = null;
  let lastPath = window.location.pathname;

  function startPathWatch() {
    if (pathWatchTimer !== null) return;
    lastPath = window.location.pathname;
    pathWatchTimer = setInterval(function () {
      const currentPath = window.location.pathname;
      if (currentPath !== lastPath) {
        lastPath = currentPath;
        autoConnect();
      }
    }, 1000);
  }

  function stopPathWatch() {
    if (pathWatchTimer === null) return;
    clearInterval(pathWatchTimer);
    pathWatchTimer = null;
  }

  // Connect on page load and on SPA-style navigation (popstate).
  document.addEventListener("DOMContentLoaded", function () {
    autoConnect();
    startPathWatch();
  });
  window.addEventListener("popstate", autoConnect);
  window.addEventListener("pagehide", function () {
    stopPathWatch();
    disconnect();
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) autoConnect();
    startPathWatch();
  });

  // ── Public API ───────────────────────────────────────

  window.BarkRealtime = {
    connect: connect,
    disconnect: disconnect,
    on: on,
    get guildId() {
      return guildId;
    },
    get connected() {
      return eventSource !== null && eventSource.readyState === EventSource.OPEN;
    },
  };
})();
