const statusCards = {
  database: document.getElementById("status-database"),
  llm: document.getElementById("status-llm"),
  telegram: document.getElementById("status-telegram"),
};

const guidanceForm = document.getElementById("guidance-form");
const effectivePrompt = document.getElementById("effective-prompt");
const telegramResult = document.getElementById("telegram-result");
const ideasList = document.getElementById("ideas-list");
const resultsSummary = document.getElementById("results-summary");
const telegramPreview = document.getElementById("telegram-preview");
const analysisStatus = document.getElementById("analysis-status");
const guidanceSaveStatus = document.getElementById("guidance-save-status");
const toast = document.getElementById("toast");

let saveGuidanceTimer = null;

function showToast(message, type = "ok") {
  toast.textContent = message;
  toast.className = `toast ${type}`;
  setTimeout(() => toast.classList.add("hidden"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const detail = payload?.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return payload;
}

function setStatusCard(card, state, value, meta = "") {
  card.className = `card status-card ${state}`;
  card.querySelector(".status-value").textContent = value;
  card.querySelector(".status-meta").textContent = meta;
}

function getGuidanceFromForm() {
  const data = new FormData(guidanceForm);
  return {
    tone: data.get("tone") || "",
    audience: data.get("audience") || "",
    topics_to_prioritize: data.get("topics_to_prioritize") || "",
    topics_to_avoid: data.get("topics_to_avoid") || "",
    custom_guidance: data.get("custom_guidance") || "",
    ideas_per_meeting: Number(data.get("ideas_per_meeting") || 4),
  };
}

function updateGuidanceSaveStatus(savedAt, storage) {
  if (!guidanceSaveStatus) return;
  if (savedAt) {
    const when = new Date(savedAt).toLocaleString();
    guidanceSaveStatus.textContent = `Saved to ${storage || "database"} at ${when}`;
  } else {
    guidanceSaveStatus.textContent = "Not saved yet";
  }
}

async function saveGuidance(showNotice = true) {
  const payload = await api("/api/guidance", {
    method: "PUT",
    body: JSON.stringify(getGuidanceFromForm()),
  });
  effectivePrompt.textContent = payload.effective_prompt;
  updateGuidanceSaveStatus(payload.saved_at, payload.storage);
  if (showNotice) {
    showToast("AI guidance saved");
  }
  return payload;
}

function scheduleGuidanceSave() {
  if (saveGuidanceTimer) {
    clearTimeout(saveGuidanceTimer);
  }
  saveGuidanceTimer = setTimeout(() => {
    saveGuidance(false).then(() => {
      showToast("Guidance auto-saved");
    }).catch((error) => {
      showToast(error.message, "error");
    });
  }, 1500);
}

function fillGuidanceForm(guidance) {
  for (const [key, value] of Object.entries(guidance)) {
    const field = guidanceForm.elements.namedItem(key);
    if (field) field.value = value ?? "";
  }
}

function renderIdeas(analysis) {
  const ideas = analysis.ideas || [];
  resultsSummary.textContent = analysis.summary || `Loaded ${ideas.length} ideas.`;
  ideasList.innerHTML = ideas.map((idea) => {
    const urgency = (idea.urgency || "medium").toLowerCase();
    const points = (idea.key_points || []).map((point) => `<li>${escapeHtml(point)}</li>`).join("");
    const research = (idea.background_research || [])
      .flatMap((block) => block.results || [])
      .slice(0, 2)
      .map((hit) => `<li>${escapeHtml(hit.title || "Result")}</li>`)
      .join("");

    return `
      <article class="idea-card">
        <div class="idea-meta">
          <span class="pill ${urgency}">${urgency}</span>
          <span class="pill">${escapeHtml(idea.estimated_length || "medium")}</span>
        </div>
        <h3>${escapeHtml(idea.title || "Untitled")}</h3>
        <p><strong>Source:</strong> ${escapeHtml(idea.meeting_source || "Unknown")}</p>
        <p><strong>Hook:</strong> ${escapeHtml(idea.hook || "")}</p>
        <p><strong>Angle:</strong> ${escapeHtml(idea.angle || "")}</p>
        ${points ? `<ul>${points}</ul>` : ""}
        ${research ? `<p><strong>Research:</strong></p><ul>${research}</ul>` : ""}
      </article>
    `;
  }).join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadStatus() {
  const status = await api("/api/status");

  if (status.database.connected) {
    setStatusCard(
      statusCards.database,
      "ok",
      "Connected",
      `${status.database.meeting_transcripts} meeting transcript(s) in lookback window`,
    );
  } else {
    setStatusCard(statusCards.database, "error", "Disconnected", status.database.error || "");
  }

  if (status.llm.providers.length) {
    setStatusCard(
      statusCards.llm,
      "ok",
      "Ready",
      `${status.llm.providers.join(", ")} · ${status.llm.model}`,
    );
  } else {
    setStatusCard(statusCards.llm, "error", "Not configured", status.llm.error || "");
  }

  if (status.telegram.configured && status.telegram.bot) {
    setStatusCard(
      statusCards.telegram,
      "ok",
      "Configured",
      `@${status.telegram.bot.username || "bot"} · chat ${status.telegram.chat_id}`,
    );
  } else if (status.telegram.configured) {
    setStatusCard(statusCards.telegram, "warn", "Needs attention", status.telegram.error || "Bot token invalid");
  } else {
    setStatusCard(statusCards.telegram, "warn", "Not configured", "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID");
  }
}

async function loadGuidance() {
  const payload = await api("/api/guidance");
  fillGuidanceForm(payload.guidance);
  effectivePrompt.textContent = payload.effective_prompt;
  updateGuidanceSaveStatus(payload.saved_at, payload.storage);
}

guidanceForm.addEventListener("input", scheduleGuidanceSave);
guidanceForm.addEventListener("change", scheduleGuidanceSave);

document.getElementById("refresh-status").addEventListener("click", async () => {
  try {
    await loadStatus();
    showToast("Status refreshed");
  } catch (error) {
    showToast(error.message, "error");
  }
});

document.getElementById("save-guidance").addEventListener("click", async () => {
  try {
    await saveGuidance(true);
  } catch (error) {
    showToast(error.message, "error");
  }
});

document.getElementById("test-telegram").addEventListener("click", async () => {
  const button = document.getElementById("test-telegram");
  button.disabled = true;
  telegramResult.classList.add("hidden");

  try {
    const message = document.getElementById("test-message").value.trim();
    const payload = await api("/api/telegram/test", {
      method: "POST",
      body: JSON.stringify(message ? { message } : {}),
    });
    telegramResult.textContent = JSON.stringify(payload, null, 2);
    telegramResult.classList.remove("hidden");
    showToast("Telegram test sent");
    await loadStatus();
  } catch (error) {
    telegramResult.textContent = error.message;
    telegramResult.classList.remove("hidden");
    showToast(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.getElementById("run-analysis").addEventListener("click", async () => {
  const button = document.getElementById("run-analysis");
  button.disabled = true;
  analysisStatus.textContent = "Running analysis… this can take up to a minute.";

  try {
    await saveGuidance(false);
    const payload = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        dry_run: document.getElementById("dry-run").checked,
        send_telegram: document.getElementById("send-telegram").checked,
        guidance: getGuidanceFromForm(),
      }),
    });

    renderIdeas(payload.analysis);
    telegramPreview.textContent = payload.telegram_preview || "";
    analysisStatus.textContent = `Generated ${payload.idea_count} ideas from ${payload.transcript_count} transcript(s).`;
    showToast(payload.telegram_sent ? "Analysis complete and sent to Telegram" : "Analysis complete");
    await loadStatus();
  } catch (error) {
    analysisStatus.textContent = error.message;
    showToast(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.getElementById("load-latest").addEventListener("click", async () => {
  try {
    const analysis = await api("/api/ideas/latest");
    renderIdeas(analysis);
    showToast("Loaded latest results");
  } catch (error) {
    showToast(error.message, "error");
  }
});

async function init() {
  try {
    await Promise.all([loadStatus(), loadGuidance()]);
    try {
      const analysis = await api("/api/ideas/latest");
      renderIdeas(analysis);
    } catch {
      // No latest analysis yet.
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

init();
