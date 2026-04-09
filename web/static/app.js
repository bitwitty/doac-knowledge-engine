/* Knowledge Engine — frontend */

let currentQuery = "";

const body       = document.body;
const queryInput = document.getElementById("query");
const submitBtn  = document.getElementById("submit-btn");
const backBtn    = document.getElementById("back-btn");
const resultsEl  = document.getElementById("results");
const queryLabel = document.getElementById("results-query-text");

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

/* ---- Example questions ---- */

document.querySelectorAll(".example-q").forEach(btn => {
  btn.addEventListener("click", () => {
    const q = btn.textContent.trim();
    queryInput.value = q;
    autoResize(queryInput);
    triggerSearch(q);
  });
});

/* ---- Back button ---- */

backBtn.addEventListener("click", () => {
  body.classList.remove("has-results");
  queryInput.focus();
});

/* ---- Search ---- */

function triggerSearch(query) {
  if (!query) return;
  currentQuery = query;
  body.classList.add("has-results");
  doSearch(query);
}

async function doSearch(query) {
  queryLabel.textContent = `"${query}"`;

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
      body: JSON.stringify({ query }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Search failed");

    renderResults(data.results);

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

  try {
    const res = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Synthesis failed");

    // Render paragraphs
    bodyEl.innerHTML = data.synthesis
      .split(/\n\n+/)
      .map(p => `<p>${esc(p.trim())}</p>`)
      .join("");

    card.querySelector(".loading-dots").remove();
  } catch (err) {
    card.querySelector(".loading-dots").remove();
    bodyEl.textContent = `Synthesis unavailable: ${err.message}`;
  }
}

function renderResults(results) {
  if (!results || results.length === 0) {
    resultsEl.innerHTML = `
      <div class="state-message">
        <h3>No moments found</h3>
        <p>Try rephrasing your question.</p>
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

queryInput.focus();
