/* ═══════════════════════════════════════════════════════════
   Olivia — Restaurant Finder
   ═══════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── DOM ───────────────────────────────────────────────
  const chatMessages    = document.getElementById('chat-messages');
  const chatForm        = document.getElementById('chat-form');
  const messageInput    = document.getElementById('message-input');
  const sendButton      = document.getElementById('send-button');
  const connectionDot   = document.getElementById('connection-dot');
  const connectionLabel = document.getElementById('connection-label');
  const statusIndicator = document.getElementById('status-indicator');

  // Setup modal
  const setupOverlay    = document.getElementById('setup-overlay');
  const setupStep1      = document.getElementById('setup-step-1');
  const setupStep2      = document.getElementById('setup-step-2');
  const addressForm     = document.getElementById('address-form');
  const addressInput    = document.getElementById('address-input');
  const detectLocationBtn = document.getElementById('detect-location-btn');
  const budgetGrid      = document.getElementById('budget-grid');
  const budgetDoneBtn   = document.getElementById('budget-done-btn');
  const dot1            = document.getElementById('dot-1');
  const dot2            = document.getElementById('dot-2');

  // Header
  const settingsBar       = document.getElementById('settings-bar');
  const userLocationText  = document.getElementById('user-location-text');
  const headerBudget      = document.getElementById('header-budget');

  // ── Constants ─────────────────────────────────────────
  const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const WS_URL      = `${WS_PROTOCOL}//${window.location.host}/ws/chat`;
  const ADDR_KEY    = 'olivia_user_address';
  const BUDGET_KEY  = 'olivia_user_budget';
  const THEME_KEY   = 'olivia_theme';

  // ── State ─────────────────────────────────────────────
  let ws               = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT  = 10;
  const BASE_DELAY     = 1000;
  const MAX_DELAY      = 30000;
  let isProcessing     = false;
  let typingEl         = null;
  const sessionId      = Math.random().toString(36).substring(2, 15);

  let userAddress  = '';
  let userBudget   = null;

  // selected budget option element
  let selectedBudgetOpt = null;

  // ── Storage ────────────────────────────────────────────
  function loadPrefs() {
    userAddress = localStorage.getItem(ADDR_KEY) || '';
    const raw = localStorage.getItem(BUDGET_KEY);
    userBudget = (raw !== null && raw !== '') ? parseInt(raw, 10) : null;
  }

  function savePrefs() {
    localStorage.setItem(ADDR_KEY, userAddress);
    localStorage.setItem(BUDGET_KEY, userBudget !== null ? String(userBudget) : '');
  }

  // ── Theme ──────────────────────────────────────────────
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    document.querySelectorAll('.theme-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.theme === theme);
    });
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY) || 'dark';
    applyTheme(saved);
  }

  document.getElementById('side-panel').addEventListener('click', (e) => {
    const btn = e.target.closest('.theme-btn');
    if (btn) applyTheme(btn.dataset.theme);
  });

  // ── Header ─────────────────────────────────────────────
  const BUDGET_LABELS = { 1: '€', 2: '€€', 3: '€€€', 4: '€€€€' };

  function updateHeader() {
    userLocationText.textContent = userAddress || '—';
    if (userBudget !== null) {
      headerBudget.textContent = BUDGET_LABELS[userBudget] || '';
      headerBudget.style.display = 'inline-block';
    } else {
      headerBudget.textContent = '';
      headerBudget.style.display = 'none';
    }
  }

  // ── Setup Modal ────────────────────────────────────────
  function showSetup(startAtStep = 1) {
    if (startAtStep === 1) {
      addressInput.value = userAddress;
      goToStep(1);
    } else {
      goToStep(2);
    }
    setupOverlay.classList.add('visible');
  }

  function hideSetup() {
    setupOverlay.classList.remove('visible');
    messageInput.focus();
  }

  function goToStep(n) {
    if (n === 1) {
      setupStep1.classList.remove('hidden');
      setupStep2.classList.add('hidden');
      dot1.classList.add('active');
      dot2.classList.remove('active');
      setTimeout(() => addressInput.focus(), 100);
    } else {
      setupStep1.classList.add('hidden');
      setupStep2.classList.remove('hidden');
      dot1.classList.remove('active');
      dot2.classList.add('active');
      // Pre-select current budget
      preselectBudget();
    }
  }

  function preselectBudget() {
    const allOpts = budgetGrid.querySelectorAll('.budget-opt');
    allOpts.forEach(btn => btn.classList.remove('selected'));
    selectedBudgetOpt = null;
    budgetDoneBtn.disabled = true;

    const target = userBudget !== null ? String(userBudget) : '';
    allOpts.forEach(btn => {
      if (btn.dataset.value === target) {
        btn.classList.add('selected');
        selectedBudgetOpt = btn;
        budgetDoneBtn.disabled = false;
      }
    });
  }

  // Address step submit
  addressForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const addr = addressInput.value.trim();
    if (!addr) {
      addressInput.classList.add('input-error');
      setTimeout(() => addressInput.classList.remove('input-error'), 1500);
      return;
    }
    userAddress = addr;
    goToStep(2);
  });

  // Detect Location button
  if (detectLocationBtn) {
    detectLocationBtn.addEventListener('click', () => {
      if (!navigator.geolocation) {
        alert('Geolocation is not supported by your browser.');
        return;
      }
      detectLocationBtn.disabled = true;
      detectLocationBtn.textContent = '⏳ Detecting location...';

      navigator.geolocation.getCurrentPosition(
        async (position) => {
          const { latitude, longitude } = position.coords;
          try {
            const res = await fetch(`/api/geocode/reverse?lat=${latitude}&lng=${longitude}`);
            const data = await res.json();
            if (data.formatted_address) {
              addressInput.value = data.formatted_address;
            } else {
              addressInput.value = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
            }
          } catch {
            addressInput.value = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
          } finally {
            detectLocationBtn.disabled = false;
            detectLocationBtn.textContent = '🎯 Detect My Location';
          }
        },
        (error) => {
          alert('Could not retrieve location. Please type your address manually.');
          detectLocationBtn.disabled = false;
          detectLocationBtn.textContent = '🎯 Detect My Location';
        },
        { timeout: 10000 }
      );
    });
  }

  // Budget option click
  budgetGrid.addEventListener('click', (e) => {
    const btn = e.target.closest('.budget-opt');
    if (!btn) return;
    budgetGrid.querySelectorAll('.budget-opt').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
    selectedBudgetOpt = btn;
    budgetDoneBtn.disabled = false;
  });

  // Budget done
  budgetDoneBtn.addEventListener('click', () => {
    if (!selectedBudgetOpt) return;
    const raw = selectedBudgetOpt.dataset.value;
    userBudget = (raw !== '') ? parseInt(raw, 10) : null;
    savePrefs();
    updateHeader();
    hideSetup();
    if (chatMessages.querySelectorAll('.user-message').length === 0) {
      const budgetLabel = userBudget !== null
        ? `max ${BUDGET_LABELS[userBudget]}`
        : 'any budget';
      addMessage(
        `Location set to **${userAddress}** · Budget: **${budgetLabel}**\n\nNow tell me what type of restaurant you're looking for!`,
        'bot'
      );
    }
  });

  // Edit button
  settingsBar.addEventListener('click', () => showSetup(1));

  // ── WebSocket ──────────────────────────────────────────
  function connect() {
    ws = new WebSocket(WS_URL);

    ws.addEventListener('open', () => {
      reconnectAttempts = 0;
      setConnectionStatus(true);
    });

    ws.addEventListener('close', () => {
      setConnectionStatus(false);
      scheduleReconnect();
    });

    ws.addEventListener('error', () => setConnectionStatus(false));

    ws.addEventListener('message', (event) => handleServerMessage(event.data));
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) {
      addMessage('Connection to server lost. Please refresh.', 'error');
      return;
    }
    const delay = Math.min(BASE_DELAY * Math.pow(2, reconnectAttempts), MAX_DELAY);
    reconnectAttempts++;
    setTimeout(connect, delay);
  }

  function setConnectionStatus(connected) {
    connectionDot.classList.toggle('connected', connected);
    connectionLabel.textContent = connected ? 'Connected' : 'Disconnected';
  }

  // ── Messages ───────────────────────────────────────────
  function handleServerMessage(raw) {
    let data;
    try { data = JSON.parse(raw); } catch {
      hideTypingIndicator(); setProcessing(false);
      addMessage(raw, 'bot'); return;
    }

    switch (data.type) {
      case 'status':
        showStatusMessage(data.message);
        break;
      case 'result':
        hideTypingIndicator(); setProcessing(false);
        if (data.data) {
          const { chat_message, places } = data.data;
          if (chat_message) addMessage(chat_message, 'bot');
          if (places && places.length) addRestaurantCards(places);
        }
        break;
      case 'error':
        hideTypingIndicator(); setProcessing(false);
        addMessage(data.message || 'An error occurred.', 'error');
        break;
      default:
        hideTypingIndicator(); setProcessing(false);
        if (data.message) addMessage(data.message, 'bot');
    }
  }

  // ── Send ───────────────────────────────────────────────
  chatForm.addEventListener('submit', (e) => { e.preventDefault(); sendMessage(); });

  messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') messageInput.value = '';
  });

  function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || isProcessing) return;

    if (!userAddress) { showSetup(1); return; }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
      addMessage('Server not connected. Please wait.', 'error');
      return;
    }

    addMessage(text, 'user');
    ws.send(JSON.stringify({
      text,
      userAddress,
      userBudget: userBudget,   // null or integer 1–4
      sessionId: sessionId,
    }));
    messageInput.value = '';
    setProcessing(true);
    showTypingIndicator();
  }

  function setProcessing(state) {
    isProcessing = state;
    sendButton.disabled = state;
    if (!state) hideStatus();
  }

  // ── Rendering ──────────────────────────────────────────
  function addMessage(content, type = 'bot') {
    const wrapper = document.createElement('div');

    if (type === 'user') {
      wrapper.className = 'message user-message';
      wrapper.innerHTML = `
        <div class="message-avatar">👤</div>
        <div class="message-bubble">
          <p>${escapeHTML(content)}</p>
          <span class="message-time">${getCurrentTime()}</span>
        </div>`;
    } else if (type === 'bot') {
      wrapper.className = 'message bot-message';
      wrapper.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-bubble">
          <p>${formatBotText(content)}</p>
          <span class="message-time">${getCurrentTime()}</span>
        </div>`;
    } else if (type === 'status') {
      wrapper.className = 'message status-message';
      wrapper.innerHTML = `
        <div class="message-bubble">
          <span class="status-dot"></span>
          <span>${escapeHTML(content)}</span>
        </div>`;
    } else if (type === 'error') {
      wrapper.className = 'message error-message';
      wrapper.innerHTML = `<div class="message-bubble">${escapeHTML(content)}</div>`;
    }

    chatMessages.appendChild(wrapper);
    scrollToBottom();
  }

  function showStatusMessage(text) {
    statusIndicator.innerHTML = `<span class="status-dot"></span><span>${escapeHTML(text)}</span>`;
    statusIndicator.classList.add('active');
    addMessage(text, 'status');
  }

  function hideStatus() { statusIndicator.classList.remove('active'); }

  // ── Typing indicator ───────────────────────────────────
  function showTypingIndicator() {
    if (typingEl) return;
    typingEl = document.createElement('div');
    typingEl.className = 'message bot-message typing-indicator-wrapper';
    typingEl.innerHTML = `
      <div class="message-avatar">🤖</div>
      <div class="message-bubble" style="width: 100%;">
        <div class="restaurant-cards-wrapper">
          <div class="skeleton-card">
            <div class="skeleton-line skeleton-header"></div>
            <div class="skeleton-line skeleton-address"></div>
            <div class="skeleton-pills">
              <div class="skeleton-line skeleton-pill"></div>
              <div class="skeleton-line skeleton-pill"></div>
            </div>
            <div class="skeleton-line skeleton-review"></div>
          </div>
          <div class="skeleton-card">
            <div class="skeleton-line skeleton-header"></div>
            <div class="skeleton-line skeleton-address"></div>
            <div class="skeleton-pills">
              <div class="skeleton-line skeleton-pill"></div>
            </div>
          </div>
        </div>
      </div>`;
    chatMessages.appendChild(typingEl);
    scrollToBottom();
  }

  function hideTypingIndicator() {
    if (typingEl) { typingEl.remove(); typingEl = null; }
  }

  // ── Restaurant Cards ───────────────────────────────────
  function addRestaurantCards(places) {
    const container = document.createElement('div');
    container.className = 'message bot-message';
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '📍';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    const wrapper = document.createElement('div');
    wrapper.className = 'restaurant-cards-wrapper';
    places.forEach((place, i) => {
      const card = createRestaurantCard(place);
      card.style.animationDelay = `${i * 150}ms`;
      wrapper.appendChild(card);
    });
    bubble.appendChild(wrapper);
    container.appendChild(avatar);
    container.appendChild(bubble);
    chatMessages.appendChild(container);
    scrollToBottom();
  }

  function createRestaurantCard(place) {
    const card = document.createElement('div');
    card.className = 'restaurant-card';

    // Rating badge (no price badge)
    let ratingHTML = '';
    if (place.rating != null && place.rating > 0) {
      ratingHTML = `
        <div class="rating-badge">
          <span class="rating-stars">${'⭐'.repeat(Math.min(Math.floor(place.rating), 5))}</span>
          <span class="rating-value">${place.rating}</span>
        </div>`;
    }

    // Full address
    let addressHTML = '';
    if (place.address) {
      addressHTML = `
        <div class="card-address">
          <span class="card-address-icon">📍</span>
          <span>${escapeHTML(place.address)}</span>
        </div>`;
    }

    // Transport row: walking pill + transit line pills
    let transportHTML = '';
    const transportTags = [];

    if (place.distance_text) {
      transportTags.push(`<span class="transport-tag">📏 ${escapeHTML(place.distance_text)}</span>`);
    }

    // Walking duration from duration_text
    const durationParts = place.duration_text ? place.duration_text.split('/').map(s => s.trim()) : [];
    for (const part of durationParts) {
      if (part.toLowerCase().includes('walk') || part.includes('پیاده')) {
        transportTags.push(`<span class="transport-tag walking">🚶 ${escapeHTML(part)}</span>`);
      }
    }

    // Transit lines from Directions API
    const lines = place.transit_lines || [];
    if (lines.length > 0) {
      // Show each transit line as its own pill
      for (const line of lines) {
        const icon = line.vehicle === 'Bus' ? '🚌'
          : line.vehicle === 'Tram' ? '🚋'
          : line.vehicle === 'Ferry' ? '⛴️'
          : '🚇';
        const stopsStr = line.stops > 0 ? ` · ${line.stops} stop${line.stops > 1 ? 's' : ''}` : '';
        const label = `${line.vehicle} ${line.name}${stopsStr}`;
        transportTags.push(`<span class="transport-tag transit">${icon} ${escapeHTML(label)}</span>`);
      }
    } else {
      // Fallback: show metro duration from duration_text if no line details
      for (const part of durationParts) {
        if (!part.toLowerCase().includes('walk') && !part.includes('پیاده')) {
          transportTags.push(`<span class="transport-tag transit">🚇 ${escapeHTML(part)}</span>`);
        }
      }
    }

    if (transportTags.length) {
      transportHTML = `<div class="transport-row">${transportTags.join('')}</div>`;
    }

    // Reviews
    const summary = place.recent_reviews_summary || '';
    const source  = place.review_source || '';
    let reviewHTML = '';
    if (summary && summary !== 'No reviews available for analysis.') {
      const srcTag = source ? `<span class="review-source-tag">${escapeHTML(source)}</span>` : '';
      reviewHTML = `
        <div class="review-summary">
          <span class="review-summary-label">📝 Reviews ${srcTag}</span>
          ${escapeHTML(summary)}
        </div>`;
    } else {
      reviewHTML = `
        <div class="review-summary no-reviews">
          <span class="review-summary-label">📝 Reviews</span>
          No reviews available.
        </div>`;
    }

    // Map & Directions buttons
    let actionButtonsHTML = '';
    const buttons = [];
    if (place.google_maps_url) {
      buttons.push(`<a class="map-button" href="${escapeAttr(place.google_maps_url)}" target="_blank" rel="noopener noreferrer">🗺️ View on Map</a>`);
    }
    if (place.coordinates && place.coordinates.lat && place.coordinates.lng) {
      const originParam = encodeURIComponent(userAddress || '');
      const destParam = `${place.coordinates.lat},${place.coordinates.lng}`;
      const dirUrl = `https://www.google.com/maps/dir/?api=1&origin=${originParam}&destination=${destParam}`;
      buttons.push(`<a class="map-button directions-button" href="${escapeAttr(dirUrl)}" target="_blank" rel="noopener noreferrer">🧭 Get Directions</a>`);
    }
    if (buttons.length > 0) {
      actionButtonsHTML = `<div class="card-actions">${buttons.join('')}</div>`;
    }

    card.innerHTML = `
      <div class="card-header">
        <span class="restaurant-name">${escapeHTML(place.name || 'Restaurant')}</span>
        <div class="card-badges">${ratingHTML}</div>
      </div>
      ${addressHTML}
      ${transportHTML}
      ${reviewHTML}
      ${actionButtonsHTML}
    `;
    return card;
  }

  // ── Helpers ────────────────────────────────────────────
  function formatBotText(text) {
    return escapeHTML(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }

  function escapeHTML(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function escapeAttr(str) {
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function getCurrentTime() {
    return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
  }

  function scrollToBottom() {
    requestAnimationFrame(() => chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' }));
  }

  // ── Init ───────────────────────────────────────────────
  function init() {
    initTheme();
    loadPrefs();
    updateHeader();
    if (!userAddress) {
      showSetup(1);
    } else if (userBudget === null && !localStorage.getItem(BUDGET_KEY)) {
      // First time with address but no budget chosen yet
      showSetup(2);
    } else {
      messageInput.focus();
    }
    connect();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
