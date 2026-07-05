function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function cardLoaderHtml() {
  return `
    <div class="card-loader" aria-hidden="true">
      <div class="card-stack">
        <span class="playing-card c1">♠</span>
        <span class="playing-card c2">♥</span>
        <span class="playing-card c3">♦</span>
      </div>
    </div>
  `;
}

function renderLoading() {
  document.getElementById("main").innerHTML = `
    <div class="loading-wrap">
      ${cardLoaderHtml()}
    </div>
  `;
}

function renderError(msg) {
  document.getElementById("main").innerHTML = `<div class="error-box">${escapeHtml(msg)}</div>`;
}

function hideSplash() {
  const splash = document.getElementById("splash");
  const app = document.getElementById("app");
  splash?.classList.add("done");
  app?.classList.remove("hidden");
  app?.classList.add("ready");
}
