/* DOAC Knowledge Engine — frontend */

let activeTopic = "";
let currentQuery = "";

const body          = document.body;
const queryInput    = document.getElementById("query");
const submitBtn     = document.getElementById("submit-btn");
const backBtn       = document.getElementById("back-btn");
const resultsEl     = document.getElementById("results");
const queryLabel    = document.getElementById("results-query-text");
const landingPills  = document.querySelectorAll("#pills .pill");
const resultsPills  = document.querySelectorAll("#pills-results .pill");
const allPills      = [...landingPills, ...resultsPills];

/* ---- Auto-resize textarea ---- */

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

queryInput.addEventListener("input", () => autoResize(queryInput));

queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    triggerSearch(queryInput.value.trim());
  }
});

submitBtn.addEventListener("click", () => triggerSearch(queryInput.value.trim()));

/* ---- Back button ---- */

backBtn.addEventListener("click", () => {
  body.classList.remove("has-results");
  queryInput.focus();
});

/* ---- Topic pills ---- */

allPills.forEach(pill => {
  pill.addEventListener("click", () => {
    const topic = pill.dataset.topic;
    const isActive = activeTopic === topic;
    activeTopic = isActive ? "" : topic;
    syncPills();

    if (body.classList.contains("has-results")) {
      // In results view: re-run current search with new filter
      doSearch(currentQuery);
    } else if (activeTopic) {
      // On landing: clicking a pill triggers a browse of that topic
      triggerSearch(activeTopic);
    }
  });
});

function syncPills() {
  allPills.forEach(p => p.classList.toggle("active", p.dataset.topic === activeTopic));
}

/* ---- Search ---- */

function triggerSearch(query) {
  if (!query) return;
  currentQuery = query;
  body.classList.add("has-results");
  doSearch(query);
}

async function doSearch(query) {
  queryLabel.textContent = `"${query}"${activeTopic ? "  ·  " + activeTopic : ""}`;

  resultsEl.innerHTML = `
    <div class="loading">
      <div class="loading-dots">
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
      </div>
      <span>Searching 2,501 moments...</span>
    </div>`;

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, topic: activeTopic }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Search failed");

    renderResults(data.results);

    // Stream synthesis after results appear
    if (data.results && data.results.length > 0) {
      streamSynthesis(query, data.results);
    }
  } catch (err) {
    resultsEl.innerHTML = `
      <div class="state-message">
        <h3>Something went wrong</h3>
        <p>${esc(err.message || "Please try again.")}</p>
      </div>`;
  }
}

async function streamSynthesis(query, results) {
  // Insert synthesis card before the moment cards
  const card = document.createElement("div");
  card.className = "synthesis-card";
  card.innerHTML = `
    <div class="synthesis-header">
      <span class="synthesis-label">What the experts say</span>
      <div class="loading-dots">
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
      </div>
    </div>
    <div class="synthesis-body" id="synthesis-body"></div>
    <div class="synthesis-guests">${
      [...new Set(results.slice(0, 6).map(r => r.guest).filter(Boolean))]
        .map(g => `<span class="synthesis-guest">${esc(g)}</span>`)
        .join("")
    }</div>`;
  resultsEl.prepend(card);

  const bodyEl = document.getElementById("synthesis-body");
  let buffer = "";

  try {
    const res = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, topic: activeTopic }),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const text = line.slice(6);
        if (text === "[DONE]") break;
        buffer += text;
        bodyEl.innerHTML = buffer;
      }
    }

    // Remove loading dots when done
    card.querySelector(".loading-dots").remove();
  } catch {
    card.querySelector(".loading-dots").remove();
    if (!buffer) bodyEl.textContent = "Synthesis unavailable.";
  }
}

function renderResults(results) {
  if (!results || results.length === 0) {
    resultsEl.innerHTML = `
      <div class="state-message">
        <h3>No moments found</h3>
        <p>Try rephrasing your question, or clear the topic filter.</p>
      </div>`;
    return;
  }

  resultsEl.innerHTML = results.map(r => `
    <article class="moment-card">
      <div class="card-header">
        <div>
          <p class="guest-name">${esc(r.guest || "Unknown Guest")}</p>
          <p class="episode-title">${esc(r.episode_title)}</p>
        </div>
        ${r.primary_topic ? `<span class="topic-badge">${esc(r.primary_topic)}</span>` : ""}
      </div>
      <blockquote class="excerpt">${esc(r.text)}</blockquote>
      <div class="card-footer">
        ${r.watch_url ? `
          <a class="watch-btn" href="${esc(r.watch_url)}" target="_blank" rel="noopener">
            Watch at <span class="ts">${esc(r.timestamp)}</span> &rarr;
          </a>` : ""}
      </div>
    </article>`).join("");
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---- Init ---- */
queryInput.focus();
