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
    <p class="synthesis-disclaimer">AI summary of transcript excerpts. Transcripts don't label speakers, so check the clips before quoting.</p>
    <div class="synthesis-guests" id="synthesis-guests"></div>`;
  resultsEl.prepend(card);

  const bodyEl = document.getElementById("synthesis-body");

  try {
    const res = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, results }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Synthesis failed");
    if (!data.synthesis) throw new Error("Empty response");

    const synthesisText = cleanSynthesis(data.synthesis, query);
    bodyEl.innerHTML = synthesisText
      .split(/\n\n+/)
      .filter(p => p.trim())
      .map(p => `<p>${esc(p.trim())}</p>`)
      .join("");

    const guestsEl = document.getElementById("synthesis-guests");
    const mentioned = [...new Set(results.slice(0, 6).map(r => displayGuest(r)).filter(g => g))]
      .filter(g => synthesisText.includes(g));
    guestsEl.innerHTML = mentioned
      .map(g => `<span class="synthesis-guest">${esc(g)}</span>`)
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

  resultsEl.innerHTML = results.map(r => {
    const name = displayGuest(r);
    return `
    <article class="moment-card">
      <div class="card-header">
        <div>
          ${name ? `<p class="guest-name">${esc(name)}</p>` : ""}
          <p class="episode-title">${esc(r.episode_title)}</p>
        </div>
      </div>
      <blockquote class="excerpt">${esc(trimExcerpt(r.text))}</blockquote>
      <div class="card-footer">
        ${r.watch_url ? `
          <a class="watch-btn" href="${esc(r.watch_url)}" target="_blank" rel="noopener">
            Watch at <span class="ts">${esc(r.timestamp)}</span> &rarr;
          </a>` : ""}
      </div>
    </article>`;
  }).join("");
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const _NOT_A_NAME = /\b(expert|advisor|assessment|whistleblower|lawyer|moment|experts)\b/i;
function displayGuest(r) {
  const g = (r.guest || "").trim();
  // If the guest field looks like a real name, use it
  if (g && !_NOT_A_NAME.test(g) && !/^most replayed/i.test(g)) return g;
  // Try to extract a name from the end of the title (e.g. "…2026! James Clear")
  const title = (r.episode_title || "").trim();
  const m = title.match(/[!.\-–—]\s*((?:Dr\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*$/);
  if (m) return m[1];
  // No name found
  return "";
}

function stripMd(str) {
  return String(str ?? "")
    .replace(/^#{1,6}\s+/gm, "")       // # headings
    .replace(/\*\*(.+?)\*\*/g, "$1")   // **bold**
    .replace(/\*(.+?)\*/g, "$1")       // *italic*
    .replace(/__(.+?)__/g, "$1")       // __bold__
    .replace(/_(.+?)_/g, "$1");        // _italic_
}

function cleanSynthesis(text, query) {
  let cleaned = stripMd(text);
  // Drop the first line if it looks like it restates the question
  const lines = cleaned.split("\n");
  const first = lines[0].trim().replace(/[?.:!]+$/, "").toLowerCase();
  const q = query.trim().replace(/[?.:!]+$/, "").toLowerCase();
  if (first && (first === q || first.includes(q) || q.includes(first))) {
    lines.shift();
    cleaned = lines.join("\n").replace(/^\n+/, "");
  }
  return cleaned;
}

function trimExcerpt(text) {
  // If the text already starts with an uppercase letter, it's fine
  const t = (text || "").trim();
  if (!t) return t;
  if (/^[A-Z]/.test(t)) return t;
  // Find the first sentence start (uppercase after ". " or "! " or "? ")
  const m = t.match(/[.!?]\s+([A-Z])/);
  if (m) return t.slice(m.index + m[0].length - 1);
  return t;
}

queryInput.focus();
