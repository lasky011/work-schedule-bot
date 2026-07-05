const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor("#0f0f0f");
  tg.setBackgroundColor("#0f0f0f");
}

function tgConfirm(msg) {
  return new Promise((resolve) => {
    if (tg?.showConfirm) tg.showConfirm(msg, resolve);
    else resolve(window.confirm(msg));
  });
}

function hapticLight() {
  try { tg?.HapticFeedback?.impactOccurred("light"); } catch (_) { /* noop */ }
}

function hapticSuccess() {
  try { tg?.HapticFeedback?.notificationOccurred("success"); } catch (_) { /* noop */ }
}

function applyTheme(themeId) {
  const nextTheme = THEMES[themeId] ? themeId : "alice_dark";
  document.body.dataset.theme = nextTheme;
  const bg = THEMES[nextTheme]?.bg || "#0f0f0f";
  try {
    tg?.setHeaderColor?.(bg);
    tg?.setBackgroundColor?.(bg);
  } catch (_) { /* noop */ }
}
