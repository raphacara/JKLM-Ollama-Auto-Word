// ==UserScript==
// @name         JKLM Ollama Auto Word
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Lit la suite de lettres sur jklm.fun et envoie une reponse via un serveur local.
// @match        *://*.jklm.fun/*
// @match        https://jklm.fun/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
  "use strict";

  if (window.location.host === "jklm.fun") {
    return;
  }

  const SERVER_URL = "http://127.0.0.1:8765/word";
  const SETTINGS_URL = "http://127.0.0.1:8765/settings";
  const POLL_INTERVAL_MS = 250;
  const VALIDATION_DELAY_MS = 550;
  const AUTO_JOIN_SCAN_INTERVAL_MS = 5000;
  const AUTO_JOIN_COOLDOWN_MS = 30000;
  const MAX_SUBMISSION_ATTEMPTS = 4;
  const SPECIAL_MODE_ATTEMPTS = 5;
  const AUTO_JOIN_STORAGE_KEY = "jklm-auto-word:auto-join";
  const HUMAN_PRESETS = {
    godlike: {
      typeMin: 0,
      typeMax: 0,
      submitMin: 0,
      submitMax: 0,
      thinkMin: 0,
      thinkMax: 0,
      mistypeProbability: 0,
      midPauseProbability: 0,
      mistypeDeleteMin: 0,
      mistypeDeleteMax: 0,
      mistypeRecoverMin: 0,
      mistypeRecoverMax: 0,
    },
    "humain rapide": {
      typeMin: 28,
      typeMax: 65,
      submitMin: 30,
      submitMax: 80,
      thinkMin: 70,
      thinkMax: 180,
      mistypeProbability: 0.01,
      midPauseProbability: 0.12,
      mistypeDeleteMin: 70,
      mistypeDeleteMax: 140,
      mistypeRecoverMin: 80,
      mistypeRecoverMax: 160,
    },
    "humain normal": {
      typeMin: 40,
      typeMax: 110,
      submitMin: 60,
      submitMax: 140,
      thinkMin: 140,
      thinkMax: 420,
      mistypeProbability: 0.05,
      midPauseProbability: 0.28,
      mistypeDeleteMin: 110,
      mistypeDeleteMax: 220,
      mistypeRecoverMin: 130,
      mistypeRecoverMax: 260,
    },
    "humain lent": {
      typeMin: 70,
      typeMax: 170,
      submitMin: 120,
      submitMax: 260,
      thinkMin: 280,
      thinkMax: 700,
      mistypeProbability: 0.08,
      midPauseProbability: 0.4,
      mistypeDeleteMin: 180,
      mistypeDeleteMax: 360,
      mistypeRecoverMin: 220,
      mistypeRecoverMax: 420,
    },
  };
  let humanMode = "humain normal";
  let HUMAN = HUMAN_PRESETS["humain normal"];

  let enabled = true;
  let inFlight = false;
  let panel;
  let activeSequence = "";
  let attemptedWords = [];
  let turnToken = 0;
  let activeRequestId = "";
  let lastWord = "-";
  let lastAttemptLabel = "-";
  let settingsLoaded = false;
  let serverOnline = false;
  let generationMaxAttempts = 30;
  let longWordsEnabled = false;
  let compoundWordsEnabled = false;
  let panelCollapsed = false;
  let autoJoinEnabled = loadAutoJoinPreference();
  let lastAutoJoinClickAt = 0;
  let lastAutoJoinScanAt = 0;

  const SELECT_STYLE = "width:100%;margin-top:6px;margin-bottom:10px;background:rgba(15,23,42,0.82);color:#f8fafc;border:1px solid rgba(148,163,184,0.18);border-radius:10px;padding:8px 10px;outline:none;";
  const LABEL_STYLE = "display:block;font-size:10px;letter-spacing:0.08em;text-transform:uppercase;color:#8da2c0;";
  const TOGGLE_CARD_STYLE = "display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border:1px solid rgba(148,163,184,0.12);border-radius:12px;background:rgba(15,23,42,0.58);";

  function loadAutoJoinPreference() {
    try {
      const stored = window.localStorage.getItem(AUTO_JOIN_STORAGE_KEY);
      return stored === null ? true : stored === "1";
    } catch (_error) {
      return true;
    }
  }

  function persistAutoJoinPreference() {
    try {
      window.localStorage.setItem(AUTO_JOIN_STORAGE_KEY, autoJoinEnabled ? "1" : "0");
    } catch (_error) {}
  }

  function nextTurnToken() {
    turnToken += 1;
    return turnToken;
  }

  function isTokenCurrent(token) {
    return token === turnToken;
  }

  function makeRequestId() {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function setStatus(message) {
    if (!panel) {
      return;
    }
    const statusNode = panel.querySelector("[data-role='status']");
    if (statusNode) {
      statusNode.textContent = message;
    }
    const chipNode = panel.querySelector("[data-role='status_chip']");
    if (chipNode) {
      chipNode.textContent = serverOnline ? "online" : "offline";
      chipNode.style.background = serverOnline ? "rgba(34,197,94,0.16)" : "rgba(239,68,68,0.16)";
      chipNode.style.color = serverOnline ? "#86efac" : "#fca5a5";
      chipNode.style.borderColor = serverOnline ? "rgba(34,197,94,0.32)" : "rgba(239,68,68,0.32)";
    }
    const compactChipNode = panel.querySelector("[data-role='compact_chip']");
    if (compactChipNode) {
      compactChipNode.textContent = serverOnline ? "online" : "offline";
      compactChipNode.style.background = serverOnline ? "rgba(34,197,94,0.16)" : "rgba(239,68,68,0.16)";
      compactChipNode.style.color = serverOnline ? "#86efac" : "#fca5a5";
      compactChipNode.style.borderColor = serverOnline ? "rgba(34,197,94,0.32)" : "rgba(239,68,68,0.32)";
    }
  }

  function setInfo(role, value) {
    if (!panel) {
      return;
    }
    const node = panel.querySelector(`[data-role='${role}']`);
    if (node) {
      node.textContent = value;
    }
  }

  function updatePanelDetails() {
    setInfo("sequence", activeSequence || "-");
    setInfo("word", lastWord || "-");
    setInfo("attempt", lastAttemptLabel || "-");
    setInfo("mode", humanMode);
    const longWordsToggle = panel?.querySelector("[data-role='long_words_toggle']");
    if (longWordsToggle) {
      longWordsToggle.checked = longWordsEnabled;
    }
    const compoundWordsToggle = panel?.querySelector("[data-role='compound_words_toggle']");
    if (compoundWordsToggle) {
      compoundWordsToggle.checked = compoundWordsEnabled;
    }
    updateAutoJoinToggleUI();
    const themeSelect = panel?.querySelector("[data-role='theme_select']");
    if (themeSelect) {
      const specialModeEnabled = longWordsEnabled || compoundWordsEnabled;
      themeSelect.disabled = specialModeEnabled;
      themeSelect.style.opacity = specialModeEnabled ? "0.45" : "1";
      themeSelect.title = specialModeEnabled ? "Ignore quand mots longs ou mots composes est coche" : "";
    }
  }

  function updateAutoJoinToggleUI() {
    if (!panel) {
      return;
    }
    const toggle = panel.querySelector("[data-role='auto_join_toggle']");
    const dot = panel.querySelector("[data-role='auto_join_dot']");
    if (!toggle || !dot) {
      return;
    }

    toggle.setAttribute("aria-pressed", autoJoinEnabled ? "true" : "false");
    toggle.style.background = autoJoinEnabled
      ? "linear-gradient(180deg, rgba(250,204,21,0.3), rgba(161,98,7,0.18))"
      : "linear-gradient(180deg, rgba(30,41,59,0.95), rgba(15,23,42,0.9))";
    toggle.style.borderColor = autoJoinEnabled ? "rgba(250,204,21,0.42)" : "rgba(148,163,184,0.2)";
    toggle.style.boxShadow = autoJoinEnabled ? "0 10px 24px rgba(250,204,21,0.18)" : "none";
    dot.style.transform = autoJoinEnabled ? "translateX(0)" : "translateX(0)";
    dot.style.background = autoJoinEnabled ? "#facc15" : "#64748b";
    dot.style.boxShadow = autoJoinEnabled ? "0 0 0 4px rgba(250,204,21,0.16)" : "none";
  }

  function setPanelCollapsed(collapsed) {
    panelCollapsed = collapsed;
    if (!panel) {
      return;
    }

    const compactButton = panel.querySelector("[data-role='compact_toggle']");
    const panelBody = panel.querySelector("[data-role='panel_body']");
    const collapseButton = panel.querySelector("[data-role='collapse_toggle']");

    if (panelCollapsed) {
      panel.style.width = "auto";
      panel.style.padding = "0";
      panel.style.background = "transparent";
      panel.style.border = "none";
      panel.style.boxShadow = "none";
      panel.style.backdropFilter = "none";
      if (panelBody) {
        panelBody.style.display = "none";
      }
      if (compactButton) {
        compactButton.style.display = "flex";
      }
      if (collapseButton) {
        collapseButton.textContent = "↗";
      }
      return;
    }

    panel.style.width = "336px";
    panel.style.padding = "14px";
    panel.style.background = "linear-gradient(160deg, rgba(8,15,32,0.96), rgba(17,24,39,0.94) 58%, rgba(12,18,30,0.96))";
    panel.style.border = "1px solid rgba(125,211,252,0.18)";
    panel.style.boxShadow = "0 22px 50px rgba(2,8,23,0.42)";
    panel.style.backdropFilter = "blur(14px)";
    if (panelBody) {
      panelBody.style.display = "block";
    }
    if (compactButton) {
      compactButton.style.display = "none";
    }
    if (collapseButton) {
      collapseButton.textContent = "−";
    }
  }

  function fillSelect(role, values, currentValue) {
    if (!panel) {
      return;
    }
    const select = panel.querySelector(`[data-role='${role}']`);
    if (!select) {
      return;
    }

    const normalizedValues = Array.from(new Set((values || []).map((value) => String(value))));
    if (currentValue && !normalizedValues.includes(String(currentValue))) {
      normalizedValues.push(String(currentValue));
    }

    const previous = select.value;
    select.innerHTML = normalizedValues
      .map((value) => `<option value="${value}">${value}</option>`)
      .join("");
    select.value = String(currentValue || previous || normalizedValues[0] || "");
  }

  function createPanel() {
    const root = document.createElement("div");
    root.style.position = "fixed";
    root.style.top = "12px";
    root.style.right = "12px";
    root.style.zIndex = "999999";
    root.style.width = "336px";
    root.style.padding = "14px";
    root.style.background = "linear-gradient(160deg, rgba(8,15,32,0.96), rgba(17,24,39,0.94) 58%, rgba(12,18,30,0.96))";
    root.style.color = "#f8fafc";
    root.style.font = "12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace";
    root.style.border = "1px solid rgba(125,211,252,0.18)";
    root.style.borderRadius = "20px";
    root.style.boxShadow = "0 22px 50px rgba(2,8,23,0.42)";
    root.style.backdropFilter = "blur(14px)";
    root.innerHTML = [
      "<button data-role='compact_toggle' style='display:none;align-items:center;gap:8px;cursor:pointer;padding:10px 14px;border-radius:999px;border:1px solid rgba(125,211,252,0.2);background:linear-gradient(160deg, rgba(8,15,32,0.96), rgba(17,24,39,0.94));color:#f8fafc;box-shadow:0 16px 32px rgba(0,0,0,0.28);'>",
      "<span style='font-weight:700;letter-spacing:0.04em;'>JKLM</span>",
      "<span data-role='compact_chip' style='padding:2px 7px;border-radius:999px;border:1px solid rgba(255,255,255,0.16);font-size:10px;text-transform:uppercase;'>online</span>",
      "</button>",
      "<div data-role='panel_body'>",
      "<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;'>",
      "<div style='display:flex;align-items:center;gap:10px;min-width:0;flex:1;'>",
      "<div style='font-weight:700;font-size:15px;letter-spacing:0.05em;white-space:nowrap;line-height:1;'>JKLM Auto</div>",
      "<div data-role='status_chip' style='display:flex;align-items:center;height:32px;padding:0 12px;border-radius:999px;border:1px solid rgba(255,255,255,0.16);font-size:10px;text-transform:uppercase;white-space:nowrap;'>offline</div>",
      "</div>",
      "<div style='display:flex;align-items:center;gap:10px;flex-shrink:0;'>",
      "<button data-role='auto_join_toggle' type='button' aria-pressed='true' style='cursor:pointer;display:flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:999px;border:1px solid rgba(148,163,184,0.18);background:linear-gradient(180deg, rgba(30,41,59,0.95), rgba(15,23,42,0.9));padding:0;transition:all 0.18s ease;color:#dbeafe;'>",
      "<span data-role='auto_join_dot' style='display:flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:999px;background:#64748b;transition:background 0.18s ease, box-shadow 0.18s ease;box-shadow:none;'>",
      "<span style='display:block;font-size:12px;line-height:1;color:#0f172a;'>↻</span>",
      "</span>",
      "</button>",
      "<button data-role='collapse_toggle' style='cursor:pointer;display:flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:999px;border:1px solid rgba(255,255,255,0.12);background:rgba(148,163,184,0.12);color:#e2e8f0;font-size:18px;line-height:1;'>−</button>",
      "</div>",
      "</div>",
      "<div style='display:flex;gap:8px;align-items:center;margin-bottom:12px;'>",
      "<div data-role='status' style='flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:10px 12px;border-radius:12px;background:linear-gradient(180deg, rgba(14,116,144,0.16), rgba(30,41,59,0.38));border:1px solid rgba(125,211,252,0.16);color:#e2e8f0;'>initialisation</div>",
      "<button data-role='toggle' style='cursor:pointer;background:#1d4ed8;color:#eff6ff;border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:7px 10px;'>ON</button>",
      "</div>",
      "<details open style='margin-bottom:10px;border:1px solid rgba(148,163,184,0.12);border-radius:14px;background:rgba(15,23,42,0.46);'>",
      "<summary style='cursor:pointer;padding:10px 12px;color:#cbd5e1;font-weight:600;'>Infos</summary>",
      "<div style='padding:0 12px 12px 12px;display:grid;grid-template-columns:auto 1fr;gap:6px 10px;color:#e5e7eb;'>",
      "<span style='color:#94a3b8;'>syllabe</span><span data-role='sequence'>-</span>",
      "<span style='color:#94a3b8;'>mot</span><span data-role='word'>-</span>",
      "<span style='color:#94a3b8;'>essai</span><span data-role='attempt'>-</span>",
      "<span style='color:#94a3b8;'>mode</span><span data-role='mode'>humain normal</span>",
      "</div>",
      "</details>",
      "<details style='border:1px solid rgba(148,163,184,0.12);border-radius:14px;background:rgba(15,23,42,0.46);'>",
      "<summary style='cursor:pointer;padding:10px 12px;color:#cbd5e1;font-weight:600;'>Reglages</summary>",
      "<div style='padding:4px 12px 12px 12px;'>",
      `<label style='${LABEL_STYLE}'>langue<select data-role='language_select' style='${SELECT_STYLE}'></select></label>`,
      `<label style='${LABEL_STYLE}'>mode humain<select data-role='human_mode_select' style='${SELECT_STYLE}'></select></label>`,
      `<label style='${LABEL_STYLE}'>modele<select data-role='model_select' style='${SELECT_STYLE}'></select></label>`,
      `<label style='${LABEL_STYLE}'>theme<select data-role='theme_select' style='${SELECT_STYLE}'></select></label>`,
      "<div style='margin:10px 0 12px 0;border-top:1px solid rgba(148,163,184,0.14);'></div>",
      "<div style='margin-bottom:10px;text-align:center;font-size:10px;letter-spacing:0.16em;text-transform:uppercase;color:#7dd3fc;'>Big LLM Only</div>",
      `<div style='${TOGGLE_CARD_STYLE};margin-top:2px;'>`,
      "<div><div style='color:#e2e8f0;font-weight:600;'>Longs</div><div style='color:#7c8aa0;font-size:11px;'>20+ caracteres</div></div>",
      "<input data-role='long_words_toggle' type='checkbox' style='width:16px;height:16px;accent-color:#22c55e;cursor:pointer;' />",
      "</div>",
      `<div style='${TOGGLE_CARD_STYLE};margin-top:10px;'>`,
      "<div><div style='color:#e2e8f0;font-weight:600;'>Composes</div><div style='color:#7c8aa0;font-size:11px;'>avec tiret</div></div>",
      "<input data-role='compound_words_toggle' type='checkbox' style='width:16px;height:16px;accent-color:#f59e0b;cursor:pointer;' />",
      "</div>",
      "</div>",
      "</details>",
      "</div>",
    ].join("");
    document.body.appendChild(root);

    const button = root.querySelector("[data-role='toggle']");
    button.addEventListener("click", () => {
      enabled = !enabled;
      button.textContent = enabled ? "ON" : "OFF";
      setStatus(enabled ? "actif" : "pause");
    });

    const compactButton = root.querySelector("[data-role='compact_toggle']");
    compactButton.addEventListener("click", () => {
      setPanelCollapsed(false);
    });

    const collapseButton = root.querySelector("[data-role='collapse_toggle']");
    collapseButton.addEventListener("click", () => {
      setPanelCollapsed(true);
    });

    const autoJoinToggle = root.querySelector("[data-role='auto_join_toggle']");
    autoJoinToggle.addEventListener("click", () => {
      autoJoinEnabled = !autoJoinEnabled;
      persistAutoJoinPreference();
      setStatus(autoJoinEnabled ? "auto-join actif" : "auto-join coupe");
      updatePanelDetails();
    });

    const wiring = [
      ["language_select", "language"],
      ["human_mode_select", "human_mode"],
      ["model_select", "model"],
      ["theme_select", "lexical_theme"],
    ];
    for (const [role, key] of wiring) {
      const select = root.querySelector(`[data-role='${role}']`);
      select.addEventListener("change", () => {
        saveSetting(key, select.value);
      });
    }

    const longWordsToggle = root.querySelector("[data-role='long_words_toggle']");
    longWordsToggle.addEventListener("change", () => {
      longWordsEnabled = longWordsToggle.checked;
      saveSetting("long_words", longWordsEnabled);
      updatePanelDetails();
    });

    const compoundWordsToggle = root.querySelector("[data-role='compound_words_toggle']");
    compoundWordsToggle.addEventListener("change", () => {
      compoundWordsEnabled = compoundWordsToggle.checked;
      saveSetting("compound_words", compoundWordsEnabled);
      updatePanelDetails();
    });

    panel = root;
    setStatus("actif");
    updatePanelDetails();
    setPanelCollapsed(false);
  }

  function applyHumanMode(mode) {
    const normalized = String(mode || "humain normal").toLowerCase();
    const aliases = {
      discret: "humain rapide",
      normal: "humain normal",
      instantane: "godlike",
    };
    const resolved = aliases[normalized] || normalized;
    humanMode = HUMAN_PRESETS[resolved] ? resolved : "humain normal";
    HUMAN = HUMAN_PRESETS[humanMode];
    updatePanelDetails();
  }

  function findSequenceNode() {
    const selectors = [
      ".syllable",
      ".syllable",
      "[class*='syllable']",
      "[data-testid*='syllable']",
      ".bp-syllable",
      ".round .text",
    ];

    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node && node.textContent && node.textContent.trim()) {
        return node;
      }
    }

    const nodes = Array.from(document.querySelectorAll("div, span"));
    return nodes.find((node) => {
      const text = (node.textContent || "").trim();
      return /^[A-Za-z]{1,4}$/.test(text) && node.getBoundingClientRect().width > 0;
    }) || null;
  }

  function findInput() {
    const selectors = [
      ".selfTurn input",
      "input[type='text']",
      "input[maxlength]",
      "input",
      "textarea",
    ];

    for (const selector of selectors) {
      const input = document.querySelector(selector);
      if (input && !input.disabled && input.offsetParent !== null) {
        return input;
      }
    }

    return null;
  }

  function clearInput(input) {
    input.focus();
    input.value = "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function randomBetween(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function sendEvent(event, payload = {}) {
    GM_xmlhttpRequest({
      method: "POST",
      url: "http://127.0.0.1:8765/event",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ event, ...payload }),
      onload: () => {},
      onerror: () => {},
    });
  }

  function loadRemoteSettings() {
    GM_xmlhttpRequest({
      method: "GET",
      url: SETTINGS_URL,
      onload: (response) => {
        if (response.status < 200 || response.status >= 300) {
          serverOnline = false;
          settingsLoaded = false;
          updatePanelDetails();
          return;
        }
        try {
          const payload = JSON.parse(response.responseText);
          serverOnline = true;
          generationMaxAttempts = Number(payload.max_generation_attempts) || generationMaxAttempts;
          longWordsEnabled = Boolean(payload.long_words);
          compoundWordsEnabled = Boolean(payload.compound_words);
          applyHumanMode(payload.human_mode);
          fillSelect("language_select", payload.options?.languages, payload.language);
          fillSelect("human_mode_select", payload.options?.human_modes, payload.human_mode);
          fillSelect("model_select", payload.options?.models, payload.model);
          fillSelect("theme_select", payload.options?.lexical_themes, payload.lexical_theme);
          settingsLoaded = true;
          updatePanelDetails();
        } catch (_error) {}
      },
      onerror: () => {
        serverOnline = false;
        settingsLoaded = false;
        updatePanelDetails();
      },
    });
  }

  function saveSetting(key, value) {
    if (!settingsLoaded) {
      return;
    }
    setStatus(`maj ${key}...`);
    GM_xmlhttpRequest({
      method: "POST",
      url: SETTINGS_URL,
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ [key]: value }),
      onload: (response) => {
        if (response.status < 200 || response.status >= 300) {
          setStatus(`erreur ${key}`);
          return;
        }
        if (key === "human_mode") {
          applyHumanMode(value);
        }
        setStatus("reglages ok");
        loadRemoteSettings();
      },
      onerror: () => setStatus(`erreur ${key}`),
    });
  }

  function cancelActiveRequest(detail = "tour termine") {
    if (!activeRequestId) {
      return;
    }
    const requestId = activeRequestId;
    activeRequestId = "";
    GM_xmlhttpRequest({
      method: "POST",
      url: "http://127.0.0.1:8765/cancel",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ request_id: requestId }),
      onload: () => {},
      onerror: () => {},
    });
    sendEvent("cancelled", { detail });
  }

  async function typeWord(input, word, sequence) {
    const token = turnToken;
    clearInput(input);
    input.focus();
    sendEvent("typing", { sequence, word });
    await sleep(randomBetween(HUMAN.thinkMin, HUMAN.thinkMax));
    if (!isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
      return false;
    }

    for (let index = 0; index < word.length; index += 1) {
      if (!isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
        return false;
      }
      const char = word[index];
      const shouldPause = index > 0 && Math.random() < HUMAN.midPauseProbability;
      if (shouldPause) {
        await sleep(randomBetween(90, 220));
      }

      const shouldMistype =
        word.length >= 5 &&
        index < word.length - 1 &&
        index > 0 &&
        Math.random() < HUMAN.mistypeProbability;

      if (shouldMistype) {
        const fakeChar = String.fromCharCode(97 + randomBetween(0, 25));
        input.value += fakeChar;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await sleep(randomBetween(HUMAN.mistypeDeleteMin, HUMAN.mistypeDeleteMax));
        input.value = input.value.slice(0, -1);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await sleep(randomBetween(HUMAN.mistypeRecoverMin, HUMAN.mistypeRecoverMax));
      }

      input.value += char;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await sleep(randomBetween(HUMAN.typeMin, HUMAN.typeMax));
    }
    return true;
  }

  function submitInput(input, word) {
    const form = input.closest("form") || document.querySelector(".selfTurn form");
    input.focus();
    if (form) {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      return;
    }

    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", code: "Enter" }));
    input.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter", code: "Enter" }));
  }

  function hasSpecialWordMode() {
    return longWordsEnabled || compoundWordsEnabled;
  }

  function getSpecialModeAttemptBudget() {
    return Math.max(1, Math.min(SPECIAL_MODE_ATTEMPTS, generationMaxAttempts));
  }

  function getFallbackAttemptBudget() {
    return Math.max(1, generationMaxAttempts - getSpecialModeAttemptBudget());
  }

  function fetchWord(sequence, excludedWords = [], requestId, overrides = {}) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: "POST",
        url: SERVER_URL,
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify({ sequence, exclude: excludedWords, request_id: requestId, overrides }),
        onload: (response) => {
          if (response.status < 200 || response.status >= 300) {
            reject(new Error(`HTTP ${response.status}`));
            return;
          }
          try {
            const payload = JSON.parse(response.responseText);
            resolve(payload.word || "jsp mdr");
          } catch (error) {
            reject(error);
          }
        },
        onerror: () => reject(new Error("server unreachable")),
      });
    });
  }

  async function requestWord(sequence, excludedWords, overrides = {}) {
    const requestId = makeRequestId();
    activeRequestId = requestId;
    try {
      return await fetchWord(sequence, excludedWords, requestId, overrides);
    } finally {
      if (activeRequestId === requestId) {
        activeRequestId = "";
      }
    }
  }

  async function requestWordWithStrategy(sequence, excludedWords, token) {
    if (!hasSpecialWordMode()) {
      return {
        word: await requestWord(sequence, excludedWords),
        usedFallback: false,
      };
    }

    const specialWord = await requestWord(sequence, excludedWords, {
      long_words: longWordsEnabled,
      compound_words: compoundWordsEnabled,
      max_attempts: getSpecialModeAttemptBudget(),
    });
    if (!isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
      return { word: "jsp mdr", usedFallback: false };
    }
    if (specialWord && specialWord !== "jsp mdr") {
      return { word: specialWord, usedFallback: false };
    }

    setStatus("fallback normal...");
    sendEvent("fallback", {
      sequence,
      detail: `special ${getSpecialModeAttemptBudget()} puis normal ${getFallbackAttemptBudget()}`,
    });

    return {
      word: await requestWord(sequence, excludedWords, {
        long_words: false,
        compound_words: false,
        max_attempts: getFallbackAttemptBudget(),
      }),
      usedFallback: true,
    };
  }

  function isSameTurnStillActive(sequence) {
    const selfTurn = document.querySelector(".selfTurn");
    const sequenceNode = findSequenceNode();
    if (!selfTurn || selfTurn.hidden || !sequenceNode) {
      return false;
    }
    return (sequenceNode.textContent || "").trim() === sequence;
  }

  function isVisible(node) {
    if (!node || !(node instanceof Element)) {
      return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function getNormalizedText(node) {
    return (node?.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function matchesAutoJoinText(text) {
    return /(auto[\s-]?join|next room|next game|prochaine room|partie suivante)/i.test(text);
  }

  function triggerSiteControl(control) {
    const target = control instanceof HTMLElement ? control : null;
    if (!target) {
      return false;
    }

    const eventOptions = { bubbles: true, cancelable: true, composed: true };
    target.dispatchEvent(new PointerEvent("pointerdown", eventOptions));
    target.dispatchEvent(new MouseEvent("mousedown", eventOptions));
    target.dispatchEvent(new PointerEvent("pointerup", eventOptions));
    target.dispatchEvent(new MouseEvent("mouseup", eventOptions));
    target.click();
    return true;
  }

  function findJoinGameButton() {
    const nodes = Array.from(document.querySelectorAll("button, [role='button'], a, div, span"));
    for (const node of nodes) {
      if (panel?.contains(node) || !isVisible(node)) {
        continue;
      }
      const text = getNormalizedText(node);
      if (text === "rejoindre la partie" || text === "join game" || text === "join the game") {
        return node.closest("button, [role='button'], a") || node;
      }
    }
    return null;
  }

  function maybeAutoJoinGame() {
    if (!autoJoinEnabled) {
      return;
    }
    const now = Date.now();
    if (now - lastAutoJoinClickAt < AUTO_JOIN_COOLDOWN_MS) {
      return;
    }
    if (now - lastAutoJoinScanAt < AUTO_JOIN_SCAN_INTERVAL_MS) {
      return;
    }
    lastAutoJoinScanAt = now;

    const joinButton = findJoinGameButton();
    if (!joinButton) {
      return;
    }

    if (triggerSiteControl(joinButton)) {
      lastAutoJoinClickAt = now;
      lastAutoJoinScanAt = now;
      setStatus("rejoindre la partie");
    }
  }

  async function tryWord(sequence, input, token) {
    if (!isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
      return;
    }
    setStatus(`cherche: ${sequence}`);
    const { word, usedFallback } = await requestWordWithStrategy(sequence, attemptedWords, token);
    if (!isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
      return;
    }
    if (!word || word === "jsp mdr") {
      lastWord = "-";
      updatePanelDetails();
      setStatus(usedFallback ? `aucun mot meme en normal` : `aucun mot pour ${sequence}`);
      return;
    }

    attemptedWords.push(word);
    lastWord = word;
    lastAttemptLabel = `${attemptedWords.length}/${generationMaxAttempts}`;
    updatePanelDetails();
    setStatus(`reponse: ${word}`);
    sendEvent("proposed", { sequence, word });
    const typed = await typeWord(input, word, sequence);
    if (!typed || !isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
      const latestInput = findInput();
      if (latestInput) {
        clearInput(latestInput);
      }
      return;
    }
    await sleep(randomBetween(HUMAN.submitMin, HUMAN.submitMax));
    if (!isTokenCurrent(token) || !isSameTurnStillActive(sequence)) {
      const latestInput = findInput();
      if (latestInput) {
        clearInput(latestInput);
      }
      return;
    }
    submitInput(input, word);
    sendEvent("submitted", { sequence, word });

    window.setTimeout(async () => {
      if (!enabled || !isTokenCurrent(token)) {
        return;
      }
      if (!isSameTurnStillActive(sequence)) {
        setStatus(`valide: ${word}`);
        sendEvent("accepted", { sequence, word });
        return;
      }
      if (attemptedWords.length >= MAX_SUBMISSION_ATTEMPTS) {
        setStatus(`refuse: ${word}`);
        sendEvent("rejected", { sequence, word });
        return;
      }

      const nextInput = findInput();
      if (nextInput) {
        clearInput(nextInput);
      }
      setStatus(`refuse, retry ${attemptedWords.length + 1}`);
      lastAttemptLabel = `${attemptedWords.length + 1}/${generationMaxAttempts}`;
      updatePanelDetails();
      sendEvent("retry", {
        sequence,
        word,
        detail: `tentative ${attemptedWords.length + 1}/${generationMaxAttempts}`,
      });
      try {
        await tryWord(sequence, nextInput || input, token);
      } catch (error) {
        setStatus(`erreur: ${error.message}`);
      }
    }, VALIDATION_DELAY_MS);
  }

  async function tick() {
    maybeAutoJoinGame();

    if (!enabled || inFlight) {
      return;
    }

    const selfTurn = document.querySelector(".selfTurn");
    if (!selfTurn || selfTurn.hidden) {
      activeSequence = "";
      attemptedWords = [];
      lastWord = "-";
      lastAttemptLabel = "-";
      nextTurnToken();
      cancelActiveRequest("fin du tour");
      const input = findInput();
      if (input) {
        clearInput(input);
      }
      updatePanelDetails();
      setStatus("attente tour");
      return;
    }

    const sequenceNode = findSequenceNode();
    const input = findInput();
    if (!sequenceNode || !input) {
      setStatus(!sequenceNode ? "syllabe introuvable" : "champ introuvable");
      return;
    }

    const sequence = (sequenceNode.textContent || "").trim();
    if (!sequence) {
      return;
    }

    if (sequence !== activeSequence) {
      cancelActiveRequest("syllabe changee");
      activeSequence = sequence;
      attemptedWords = [];
      lastWord = "-";
      lastAttemptLabel = `1/${generationMaxAttempts}`;
      nextTurnToken();
      updatePanelDetails();
    }

    if (attemptedWords.length > 0) {
      return;
    }

    inFlight = true;
    const currentToken = turnToken;

    try {
      await tryWord(sequence, input, currentToken);
    } catch (error) {
      setStatus(`erreur: ${error.message}`);
    } finally {
      inFlight = false;
    }
  }

  function boot() {
    createPanel();
    loadRemoteSettings();
    setStatus("attente tour");
    window.setInterval(tick, POLL_INTERVAL_MS);
    window.setInterval(loadRemoteSettings, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
