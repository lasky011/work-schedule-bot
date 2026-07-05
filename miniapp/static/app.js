let tab = "schedule";
let weekOffset = 0;
let monthOffset = 0;
let scheduleMode = "week";
let teamDayOffset = 0;
let profile = null;
let peopleScreen = "list";
let colleagueView = null;
let colleagueWeekOffset = 0;
let colleagueScheduleMode = "week";
let colleagueMonthOffset = 0;
let colleagueReturnTab = null;
let comparePick = [];
let comparePeriods = null;
let comparePeriodIndex = 0;
let salaryPeriods = null;
let salaryPeriodIndex = 0;
let namePickRole = null;

function parseStartParams() {
  const p = new URLSearchParams(window.location.search);
  const day = p.get("day");
  return {
    view: p.get("view"),
    teamOffset: day === "tomorrow" ? 1 : 0,
    hoursDate: p.get("date"),
  };
}

function shiftLabel(day) {
  if (!day.working) return "—";
  if (day.shift_type === "morning") return "♠ утро";
  if (day.shift_type === "evening") return "♥ вечер";
  return day.label || "—";
}

function shiftClass(day) {
  if (!day.working) return "off";
  return day.shift_type === "morning" ? "morning" : "evening";
}

function logShiftLabel(entry) {
  if (entry.shift_type === "morning") return "♠ утро";
  if (entry.shift_type === "evening") return "♥ вечер";
  return entry.label || "смена";
}

function setNavHoursBadge(show) {
  document.querySelector('.nav-btn[data-tab="analytics"]')?.classList.toggle("has-badge", !!show);
}

function setNavSalaryBadge(show) {
  document.querySelector('.nav-btn[data-tab="salary"]')?.classList.toggle("has-salary-badge", !!show);
}

async function refreshNavBadges() {
  if (!profile?.track_hours) {
    setNavHoursBadge(false);
    setNavSalaryBadge(false);
    return;
  }
  try {
    const data = await api("/api/analytics");
    const missing = data.hours_status?.missing_past_days?.length || 0;
    setNavHoursBadge(missing > 0);
    setNavSalaryBadge(missing > 0);
  } catch {
    setNavHoursBadge(false);
    setNavSalaryBadge(false);
  }
}

async function loadProfile() {
  profile = await api("/api/me");
  if (!profile.registered) {
    applyTheme("alice_dark");
    hideSplash();
    document.getElementById("nav")?.classList.add("hidden");
    document.getElementById("screen-title").textContent = "кто ты?";
    document.getElementById("screen-subtitle").textContent = "выбери отдел и имя";
    await renderNamePicker("main", { onboarding: true });
    return false;
  }
  applyTheme(profile.theme || "alice_dark");
  refreshNavBadges();
  return true;
}

async function renderNamePicker(targetId, { onboarding = false } = {}) {
  const el = document.getElementById(targetId);
  if (!el) return;
  el.innerHTML = `<div class="loading-wrap">${cardLoaderHtml()}</div>`;

  const data = await api("/api/departments");

  if (!namePickRole) {
    const depts = data.departments.map((d) => `
      <button type="button" class="name-pick-dept" data-role="${escapeAttr(d.role)}">${escapeHtml(d.role_label)}</button>
    `).join("");
    el.innerHTML = `
      <div class="hours-title">${onboarding ? "привет в зазеркалье" : "сменить имя"}</div>
      <div class="setting-desc" style="margin-bottom:12px">${onboarding ? "выбери подразделение" : "шаг 1 — отдел"}</div>
      ${depts}
      ${!onboarding ? `<button type="button" class="btn name-pick-back" id="name-pick-cancel">назад</button>` : ""}
    `;
    el.querySelectorAll(".name-pick-dept").forEach((btn) => {
      btn.addEventListener("click", () => {
        namePickRole = btn.dataset.role;
        renderNamePicker(targetId, { onboarding });
      });
    });
    document.getElementById("name-pick-cancel")?.addEventListener("click", () => {
      namePickRole = null;
      renderSettingsContent();
    });
    return;
  }

  const dept = data.departments.find((d) => d.role === namePickRole);
  const names = (dept?.names || []).map((n) => `
    <button type="button" class="name-pick-btn" data-name="${escapeAttr(n)}">${escapeHtml(n)}</button>
  `).join("");

  el.innerHTML = `
    <div class="hours-title">${escapeHtml(dept?.role_label || namePickRole)}</div>
    <div class="setting-desc" style="margin-bottom:8px">выбери имя</div>
    <div class="name-pick-names">${names}</div>
    <button type="button" class="btn name-pick-back" id="name-pick-back">← отдел</button>
  `;

  document.getElementById("name-pick-back")?.addEventListener("click", () => {
    namePickRole = null;
    renderNamePicker(targetId, { onboarding });
  });

  el.querySelectorAll(".name-pick-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        profile = await api("/api/me/profile", {
          method: "PATCH",
          body: JSON.stringify({ name: btn.dataset.name, role: namePickRole }),
        });
        namePickRole = null;
        applyTheme(profile.theme || "alice_dark");
        tg?.HapticFeedback?.notificationOccurred("success");
        if (onboarding) {
          document.getElementById("nav")?.classList.remove("hidden");
          refreshNavBadges();
          setTab("schedule");
          return;
        }
        renderSettingsContent();
      } catch (e) {
        tg?.showAlert?.(e.message);
      }
    });
  });
}

function scheduleModeToggleHtml() {
  return `
    <div class="schedule-toggle">
      <button type="button" class="btn${scheduleMode === "week" ? " active" : ""}" data-mode="week">неделя</button>
      <button type="button" class="btn${scheduleMode === "month" ? " active" : ""}" data-mode="month">месяц</button>
    </div>
  `;
}

function bindScheduleModeToggle() {
  document.querySelectorAll(".schedule-toggle [data-mode]").forEach((btn) => {
    btn.onclick = () => {
      scheduleMode = btn.dataset.mode;
      renderSchedule();
    };
  });
}

function todayCardHtml(today, tomorrow) {
  let todayLine = "нет данных";
  if (today) {
    const dayLabel = formatScheduleDay(today);
    if (today.working) {
      todayLine = `${dayLabel} · ${shiftLabel(today)}`;
      if (today.hours) todayLine += ` · ${today.hours} ч`;
    } else if (today.published === false) {
      todayLine = `${dayLabel} · график не опубликован`;
    } else {
      todayLine = `${dayLabel} · выходной`;
    }
  }

  let tomorrowLine = "";
  if (tomorrow) {
    if (tomorrow.working) {
      tomorrowLine = `завтра · ${shiftLabel(tomorrow)}`;
      if (tomorrow.hours) tomorrowLine += ` · ${tomorrow.hours} ч`;
    } else if (tomorrow.published === false) {
      tomorrowLine = "завтра · график не опубликован";
    } else {
      tomorrowLine = "завтра · выходной";
    }
  }

  const actions = today?.date
    ? `<div class="today-actions">
        <button type="button" class="btn today-action-btn" id="today-open-team">кто на смене</button>
      </div>`
    : "";

  return `
    <div class="card today-card">
      <div class="card-label">сегодня</div>
      <div class="card-title">${escapeHtml(todayLine)}</div>
      ${tomorrowLine ? `<div class="card-divider"></div><div class="card-meta">${escapeHtml(tomorrowLine)}</div>` : ""}
      ${actions}
    </div>
  `;
}

function bindTodayCard() {
  document.getElementById("today-open-team")?.addEventListener("click", () => {
    hapticLight();
    teamDayOffset = 0;
    setTab("team");
  });
}

function weekViewHintHtml(header) {
  return `<div class="week-view-hint">ниже — просмотр недели ${escapeHtml(header)}</div>`;
}

function monthShiftShort(day) {
  if (!day.published) return "·";
  if (!day.working) return "—";
  if (day.shift_type === "morning") return "♠";
  if (day.shift_type === "evening") return "♥";
  return "•";
}

function weekDayCellHtml(d) {
  return `
    <div class="day-cell day-pick${d.is_today ? " today" : ""}" data-date="${d.date}" role="button">
      <div class="day-wd">${d.weekday}</div>
      <div class="day-num">${d.day}</div>
      <div class="day-shift ${shiftClass(d)}">${shiftLabel(d)}</div>
    </div>
  `;
}

function monthDayCellHtml(d) {
  const unpublished = !d.published;
  const cls = [
    "month-cell",
    "month-pick",
    d.is_today ? "today" : "",
    unpublished ? "unpublished" : shiftClass(d),
  ].filter(Boolean).join(" ");
  return `
    <div class="${cls}" data-date="${d.date}" role="button">
      <div class="month-num">${d.day}</div>
      <div class="month-mark">${monthShiftShort(d)}</div>
    </div>
  `;
}

function bindDayPickers(root = document) {
  root.querySelectorAll(".day-pick, .month-pick").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.date) openDaySheet(el.dataset.date);
    });
  });
}

function closeDaySheet() {
  resetSheetPanel(document.getElementById("day-sheet"));
  const sheet = document.getElementById("day-sheet");
  sheet?.classList.remove("open");
  setTimeout(() => sheet?.classList.add("hidden"), 400);
}

async function openDaySheet(dateStr) {
  const sheet = document.getElementById("day-sheet");
  const content = document.getElementById("day-content");
  if (!sheet || !content) return;

  sheet.classList.remove("hidden");
  content.innerHTML = `<div class="loading-wrap">${cardLoaderHtml()}</div>`;
  requestAnimationFrame(() => sheet.classList.add("open"));

  try {
    const data = await api(`/api/team/date?date=${encodeURIComponent(dateStr)}`);
    if (!data.published) {
      content.innerHTML = `
        <div class="hours-title">${data.weekday} · ${data.header}</div>
        <div class="empty-team" style="margin-top:16px">график на этот день ещё не опубликован</div>
      `;
      return;
    }

    const working = (data.departments || []).map((dep) => `
      <div class="role-block">
        <div class="role-title">${escapeHtml(dep.role_label)} · ${dep.people.length}</div>
        <div class="people-list">
          ${dep.people.map((n) => personChipBtnHtml(n, dep.role, dep.role_label)).join("")}
        </div>
      </div>
    `).join("") || `<div class="empty-team">никого на смене</div>`;

    const offRows = (data.off || []).map((p) => `
      <div class="off-row">
        <span>${escapeHtml(p.name)}</span>
        <span class="off-role">${escapeHtml(p.role_label || "")}</span>
      </div>
    `).join("") || `<div class="hours-meta">все в списке работают или нет данных</div>`;

    content.innerHTML = `
      <div class="hours-title">${escapeHtml(data.weekday)} · ${escapeHtml(data.header)}</div>
      <div class="card-meta">${data.total_working} на смене</div>
      <div class="card" style="margin-top:12px">
        <div class="card-label">работают</div>
        ${working}
      </div>
      <div class="off-block">
        <div class="off-title">выходной — возможная замена</div>
        ${offRows}
      </div>
    `;
    bindColleagueChipButtons(content, "schedule");
  } catch (e) {
    content.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
}

async function renderSchedule() {
  renderLoading();
  try {
    if (scheduleMode === "month") {
      await renderScheduleMonth();
      return;
    }

    const data = await api(`/api/schedule/week?offset=${weekOffset}`);
    const daysHtml = data.days.map((d) => weekDayCellHtml(d)).join("");

    document.getElementById("main").innerHTML = `
      ${hoursEntryButtonHtml()}
      ${todayCardHtml(data.today, data.tomorrow)}
      ${weekOffset !== 0 ? weekViewHintHtml(data.header) : ""}
      ${scheduleModeToggleHtml()}
      <div class="card-label">неделя · ${data.header}</div>
      <div class="week-grid">${daysHtml}</div>
      <div class="week-nav">
        <button type="button" class="btn" id="prev-week">← пред</button>
        <button type="button" class="btn btn-primary" id="next-week">след →</button>
      </div>
      <p class="quote">all you need is love</p>
    `;

    bindScheduleModeToggle();
    bindDayPickers();
    bindHoursEntryButton();
    bindTodayCard();
    document.getElementById("prev-week").onclick = () => { weekOffset -= 1; renderSchedule(); };
    document.getElementById("next-week").onclick = () => { weekOffset += 1; renderSchedule(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderScheduleMonth() {
  const data = await api(`/api/schedule/month?offset=${monthOffset}`);
  const wdHeader = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    .map((w) => `<div class="month-wd">${w}</div>`).join("");

  let pad = "";
  for (let i = 0; i < data.first_weekday; i += 1) {
    pad += `<div class="month-cell empty" aria-hidden="true"></div>`;
  }

  const cells = data.days.map((d) => monthDayCellHtml(d)).join("");

  const todayEntry = monthOffset === 0 ? data.days.find((d) => d.is_today) : null;
  const tomorrowEntry = todayEntry
    ? data.days.find((d) => d.day === todayEntry.day + 1)
    : null;

  const topCard = monthOffset === 0
    ? todayCardHtml(todayEntry, tomorrowEntry)
    : `<div class="card week-preview-card"><div class="card-label">просмотр</div><div class="card-title">${escapeHtml(data.header)}</div></div>`;

  document.getElementById("main").innerHTML = `
    ${hoursEntryButtonHtml()}
    ${topCard}
    ${scheduleModeToggleHtml()}
    <div class="card-label">${data.header}</div>
    <div class="month-legend">
      <span>♠ утро</span><span>♥ вечер</span><span>— вых</span><span>· нет графика</span>
    </div>
    <div class="month-grid">
      ${wdHeader}
      ${pad}
      ${cells}
    </div>
    <div class="month-stats">
      <span>${data.stats.working} смен</span>
      <span>${data.stats.off} вых</span>
    </div>
    <div class="week-nav">
      <button type="button" class="btn" id="prev-month">← пред</button>
      <button type="button" class="btn btn-primary" id="next-month">след →</button>
    </div>
    <p class="quote">curiouser and curiouser</p>
  `;

  bindScheduleModeToggle();
  bindDayPickers();
  bindHoursEntryButton();
  if (monthOffset === 0) bindTodayCard();
  document.getElementById("prev-month").onclick = () => { monthOffset -= 1; renderSchedule(); };
  document.getElementById("next-month").onclick = () => { monthOffset += 1; renderSchedule(); };
}

function renderHoursStatus(hs) {
  const { past_shifts, logged_shifts, future_shifts, missing_past_days, shift_log } = hs;
  const pct = past_shifts ? Math.min(100, Math.round((logged_shifts / past_shifts) * 100)) : 0;

  let summary = "";
  if (past_shifts === 0 && future_shifts === 0) {
    summary = "в этом периоде смен нет";
  } else if (past_shifts > 0) {
    summary = `${logged_shifts}/${past_shifts} смен внесены`;
  }

  let meta = "";
  if (future_shifts > 0) {
    const w = future_shifts === 1 ? "смена" : future_shifts < 5 ? "смены" : "смен";
    meta = `${future_shifts} ${w} ещё впереди`;
  }

  let alert = "";
  if (missing_past_days.length) {
    const n = missing_past_days.length;
    const w = n === 1 ? "смена" : n < 5 ? "смены" : "смен";
    alert = `<div class="warn">${n} ${w} без часов — нажми на строку</div>`;
  } else if (past_shifts > 0 && logged_shifts === past_shifts) {
    alert = `<div class="ok-msg">все прошедшие смены внесены</div>`;
  }

  const logRows = (shift_log || []).map((s) => {
    let statusClass = "ahead";
    let statusText = "впереди";
    if (s.is_past) {
      if (s.logged) {
        statusClass = "done";
        statusText = s.hours ? `${s.hours} ч` : "внесено";
      } else {
        statusClass = "pending";
        statusText = "нет часов";
      }
    }
    return `
      <div class="shift-row shift-row-editable${s.is_past ? "" : " future"}" data-date="${s.date}">
        <span class="shift-date">${s.weekday} ${s.day}</span>
        <span class="shift-name">${logShiftLabel(s)}</span>
        <span class="shift-status ${statusClass}">${statusText}</span>
      </div>
    `;
  }).join("");

  return `
    <div class="card">
      <div class="card-label">учёт часов</div>
      ${summary ? `<div class="hours-summary">${summary}</div>` : ""}
      ${past_shifts > 0 ? `
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
      ` : ""}
      ${meta ? `<div class="hours-meta">${meta}</div>` : ""}
      ${alert}
      ${logRows ? `
        <div class="shift-log">
          <div class="shift-log-title">по датам</div>
          ${logRows}
        </div>
      ` : ""}
    </div>
  `;
}

async function renderAnalytics() {
  renderLoading();
  try {
    const data = await api("/api/analytics");
    const p = data.period;
    const periodLabel = `${p.start}–${p.end}`;

    let hoursBlock = "";
    if (data.track_hours && data.hours_status) {
      hoursBlock = renderHoursStatus(data.hours_status);
    } else if (data.track_hours) {
      const pct = data.hours ? Math.min(100, Math.round((data.logged_hours / data.hours) * 100)) : 0;
      hoursBlock = `
        <div class="card">
          <div class="card-label">график vs факт</div>
          <div class="progress-wrap">
            <div class="card-meta">${data.logged_hours} / ${data.hours} ч</div>
            <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
          </div>
        </div>
      `;
    }

    const maxBar = Math.max(data.morning, data.evening, data.off, 1);
    const bar = (label, val) => `
      <div class="bar-row">
        <span style="width:48px">${label}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.round(val / maxBar * 100)}%"></div></div>
        <span>${val}</span>
      </div>
    `;

    document.getElementById("main").innerHTML = `
      ${hoursEntryButtonHtml()}
      <div class="card-label">период ${periodLabel}</div>
      <div class="stats-grid">
        <div class="stat"><div class="stat-val">${data.shifts}</div><div class="stat-label">смен</div></div>
        <div class="stat"><div class="stat-val">${data.hours}</div><div class="stat-label">часов</div></div>
        <div class="stat"><div class="stat-val">${data.morning}/${data.evening}</div><div class="stat-label">♠ / ♥</div></div>
        <div class="stat"><div class="stat-val">${data.off}</div><div class="stat-label">вых</div></div>
      </div>
      <div class="card">
        <div class="card-label">распределение</div>
        ${bar("♠ утро", data.morning)}
        ${bar("♥ вечер", data.evening)}
        ${bar("вых", data.off)}
      </div>
      ${hoursBlock}
    `;

    bindShiftEditRows();
    bindHoursEntryButton();
  } catch (e) {
    renderError(e.message);
  }
}

async function renderTeam() {
  renderLoading();
  try {
    const data = await api(`/api/team/day?offset=${teamDayOffset}`);
    const my = data.my_shift;
    let myLine = "выходной";
    let myClass = "";
    if (my?.working) {
      myClass = "working";
      myLine = shiftLabel(my);
      if (my.hours) myLine += ` · ${my.hours} ч`;
    }

    let body = "";
    if (!data.published) {
      body = `<div class="empty-team">график на этот день ещё не опубликован</div>`;
    } else if (!data.total) {
      body = `<div class="empty-team">никого на смене</div>`;
    } else {
      body = data.departments.map((dep) => `
        <div class="role-block">
          <div class="role-title">${escapeHtml(dep.role_label)} · ${dep.people.length}</div>
          <div class="people-list">
            ${dep.people.map((name) => personChipBtnHtml(name, dep.role, dep.role_label)).join("")}
          </div>
        </div>
      `).join("");
    }

    document.getElementById("main").innerHTML = `
      <div class="team-toggle">
        <button type="button" class="btn${teamDayOffset === 0 ? " active" : ""}" id="team-today">сегодня</button>
        <button type="button" class="btn${teamDayOffset === 1 ? " active" : ""}" id="team-tomorrow">завтра</button>
      </div>
      <div class="card">
        <div class="team-header">
          <div class="card-label">${escapeHtml(data.weekday)} · ${escapeHtml(data.header)}</div>
          ${data.published ? `<div class="team-total">${data.total} чел.</div>` : ""}
        </div>
        <div class="my-shift-line ${myClass}">ты · ${myLine}</div>
        <div class="card-meta" style="margin-bottom:8px">тап по имени — график коллеги</div>
        ${body}
      </div>
      <p class="quote">we're all mad here</p>
    `;

    document.getElementById("team-today").onclick = () => { teamDayOffset = 0; renderTeam(); };
    document.getElementById("team-tomorrow").onclick = () => { teamDayOffset = 1; renderTeam(); };
    bindColleagueChipButtons(document.getElementById("main"), "team");
  } catch (e) {
    renderError(e.message);
  }
}

function closeHoursSheet() {
  resetSheetPanel(document.getElementById("hours-sheet"));
  const sheet = document.getElementById("hours-sheet");
  sheet.classList.remove("open");
  setTimeout(() => sheet.classList.add("hidden"), 400);
}

function offsetDateStr(dateStr, days) {
  const d = new Date(`${dateStr}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function hoursEntryButtonHtml() {
  if (!profile?.track_hours) return "";
  return `<button type="button" class="btn hours-entry-btn" id="log-hours-btn">
    <span class="action-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="12" cy="12" r="7"/><path d="M12 9v3.5l2.5 1.5"/></svg></span>
    <span>внести смену</span>
  </button>`;
}

function bindHoursEntryButton() {
  document.getElementById("log-hours-btn")?.addEventListener("click", () => {
    hapticLight();
    openHoursPicker();
  });
}

async function openHoursPicker() {
  if (!profile?.track_hours) {
    tg?.showAlert?.("Учёт часов выключен — включи в настройках ⚙");
    return;
  }

  const sheet = document.getElementById("hours-sheet");
  const content = document.getElementById("hours-content");
  sheet.classList.remove("hidden");
  content.innerHTML = `<div class="loading-wrap">${cardLoaderHtml()}</div>`;
  requestAnimationFrame(() => sheet.classList.add("open"));

  try {
    const week = await api("/api/schedule/week?offset=0");
    const today = week.today?.date;
    const yesterday = today ? offsetDateStr(today, -1) : null;

    content.innerHTML = `
      <div class="hours-title">⏱ внести смену</div>
      <div class="setting-desc" style="margin-bottom:12px">выбери дату</div>
      <div class="hours-actions">
        ${today ? `<button type="button" class="btn btn-primary" id="hours-pick-today">сегодня</button>` : ""}
        ${yesterday ? `<button type="button" class="btn" id="hours-pick-yesterday">вчера</button>` : ""}
      </div>
    `;

    document.getElementById("hours-pick-today")?.addEventListener("click", () => openHoursSheet(today));
    document.getElementById("hours-pick-yesterday")?.addEventListener("click", () => openHoursSheet(yesterday));
  } catch (e) {
    content.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
}

function closeSettingsSheet() {
  resetSheetPanel(document.getElementById("settings-sheet"));
  const sheet = document.getElementById("settings-sheet");
  sheet.classList.remove("open");
  setTimeout(() => sheet.classList.add("hidden"), 400);
}

function resetSheetPanel(sheetEl) {
  const panel = sheetEl?.querySelector(".sheet-panel");
  if (!panel) return;
  panel.classList.remove("sheet-dragging");
  panel.style.removeProperty("transform");
  panel.style.removeProperty("transition");
}

async function refreshCurrentTab() {
  if (tab === "schedule") await renderSchedule();
  else if (tab === "team") await renderTeam();
  else if (tab === "salary") await renderSalary();
  else if (tab === "analytics") await renderAnalytics();
  refreshNavBadges();
}

function setupSheetSwipe(sheetId, closeFn) {
  const sheet = document.getElementById(sheetId);
  const panel = sheet?.querySelector(".sheet-panel");
  const dragZone = sheet?.querySelector(".sheet-drag-zone");
  if (!sheet || !panel || !dragZone) return;

  let startY = 0;
  let deltaY = 0;
  let dragging = false;
  let dragFrom = null;
  let pointerId = null;

  const scrollBody = () => panel.querySelector("#day-content, #hours-content, #settings-content");

  const finishDrag = () => {
    if (!dragging) return;
    dragging = false;
    dragFrom = null;
    pointerId = null;
    panel.classList.remove("sheet-dragging");

    if (deltaY > 48) {
      panel.style.transition = "transform 0.26s ease-out";
      panel.style.transform = "translateY(100%)";
      setTimeout(() => closeFn(), 240);
    } else {
      panel.style.transition = "transform 0.26s ease-out";
      panel.style.transform = "translateY(0)";
      setTimeout(() => resetSheetPanel(sheet), 260);
    }
    deltaY = 0;
  };

  const onMove = (clientY) => {
    if (!dragging) return;
    deltaY = Math.max(0, clientY - startY);
    panel.style.transform = `translateY(${deltaY}px)`;
  };

  const beginDrag = (clientY, source) => {
    if (!sheet.classList.contains("open")) return false;
    const body = scrollBody();
    if (source === "panel" && body && body.scrollTop > 2) return false;

    dragging = true;
    dragFrom = source;
    startY = clientY;
    deltaY = 0;
    panel.classList.add("sheet-dragging");
    panel.style.transition = "none";
    return true;
  };

  dragZone.addEventListener("pointerdown", (e) => {
    if (!beginDrag(e.clientY, "handle")) return;
    pointerId = e.pointerId;
    dragZone.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  dragZone.addEventListener("pointermove", (e) => {
    if (!dragging || dragFrom !== "handle" || e.pointerId !== pointerId) return;
    e.preventDefault();
    onMove(e.clientY);
  });

  dragZone.addEventListener("pointerup", (e) => {
    if (e.pointerId !== pointerId) return;
    try { dragZone.releasePointerCapture(e.pointerId); } catch (_) { /* noop */ }
    finishDrag();
  });

  dragZone.addEventListener("pointercancel", (e) => {
    if (e.pointerId !== pointerId) return;
    finishDrag();
  });

  dragZone.addEventListener("touchstart", (e) => {
    if (dragging) return;
    if (!beginDrag(e.touches[0].clientY, "handle")) return;
    e.preventDefault();
  }, { passive: false });

  dragZone.addEventListener("touchmove", (e) => {
    if (!dragging || dragFrom !== "handle") return;
    e.preventDefault();
    onMove(e.touches[0].clientY);
  }, { passive: false });

  dragZone.addEventListener("touchend", () => {
    if (dragFrom === "handle") finishDrag();
  });

  dragZone.addEventListener("touchcancel", () => {
    if (dragFrom === "handle") finishDrag();
  });

  panel.addEventListener("touchstart", (e) => {
    if (e.target.closest(".sheet-drag-zone")) return;
    beginDrag(e.touches[0].clientY, "panel");
  }, { passive: true });

  panel.addEventListener("touchmove", (e) => {
    if (!dragging || dragFrom !== "panel") return;
    onMove(e.touches[0].clientY);
  }, { passive: true });

  panel.addEventListener("touchend", () => {
    if (dragFrom === "panel") finishDrag();
  });

  panel.addEventListener("touchcancel", () => {
    if (dragFrom === "panel") finishDrag();
  });
}

async function patchSettings(body) {
  profile = await api("/api/me/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return profile;
}

function themeOptionsHtml(activeTheme) {
  return Object.entries(THEMES).map(([id, theme]) => `
    <button type="button" class="theme-option${activeTheme === id ? " active" : ""}" data-theme="${id}">
      <span class="theme-swatch ${id}">
        <span></span><span></span><span></span>
      </span>
      <span class="theme-copy">
        <span class="theme-name">${theme.title}</span>
        <span class="theme-note">${theme.note}</span>
      </span>
    </button>
  `).join("");
}

function renderSettingsContent() {
  const p = profile;
  const content = document.getElementById("settings-content");
  if (!content || !p) return;

  content.innerHTML = `
    <div class="sheet-title-row">
      <div class="hours-title">настройки</div>
      <div class="sheet-title-actions">
        <button type="button" class="sheet-jump-btn" id="jump-settings-theme">тема</button>
        <button type="button" class="sheet-close-btn" id="close-settings-sheet" aria-label="закрыть">✕</button>
      </div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="profile-name">${escapeHtml(p.name)}</div>
      ${p.role_label ? `<div class="setting-desc">${escapeHtml(p.role_label)}</div>` : ""}
      <button type="button" class="btn" id="change-name" style="width:100%;margin-top:10px">сменить имя</button>
    </div>
    <div class="card">
      <div class="card-label">ежедневное уведомление</div>
      <div class="setting-row">
        <div class="setting-info">
          <div class="setting-title">напоминание о смене</div>
          <div class="setting-desc">приходит в чат в заданное время</div>
        </div>
        <button type="button" class="btn toggle-btn${p.notify ? " on" : ""}" id="toggle-notify">${p.notify ? "вкл" : "выкл"}</button>
      </div>
      <div class="setting-row">
        <div class="setting-info">
          <div class="setting-title">время</div>
        </div>
        <input class="hours-input settings-time" id="notify-time" value="${p.notify_time || ""}" placeholder="09:30" />
      </div>
      <button type="button" class="btn btn-primary" id="save-notify-time" style="width:100%;margin-top:8px">сохранить время</button>
    </div>
    <div class="card">
      <div class="card-label">учёт часов</div>
      <div class="setting-row">
        <div class="setting-info">
          <div class="setting-title">вносить смены</div>
          <div class="setting-desc">зп и аналитика по факту</div>
        </div>
        <button type="button" class="btn toggle-btn${p.track_hours ? " on" : ""}" id="toggle-track">${p.track_hours ? "вкл" : "выкл"}</button>
      </div>
      <div class="setting-row">
        <div class="setting-info">
          <div class="setting-title">напоминание о часах</div>
          <div class="setting-desc">после смены — кнопка в чате</div>
        </div>
        <button type="button" class="btn toggle-btn${p.notify_hours ? " on" : ""}" id="toggle-notify-hours">${p.notify_hours ? "вкл" : "выкл"}</button>
      </div>
    </div>
    <div class="card" id="settings-theme-card">
      <div class="card-label">тема</div>
      <div class="theme-grid">
        ${themeOptionsHtml(p.theme || "alice_dark")}
      </div>
    </div>
  `;

  document.getElementById("close-settings-sheet")?.addEventListener("click", () => {
    hapticLight();
    closeSettingsSheet();
  });

  document.getElementById("jump-settings-theme")?.addEventListener("click", () => {
    hapticLight();
    document.getElementById("settings-theme-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  document.getElementById("change-name")?.addEventListener("click", () => {
    namePickRole = null;
    renderNamePicker("settings-content");
  });

  content.querySelectorAll(".theme-option").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const nextTheme = btn.dataset.theme;
      if (!nextTheme || nextTheme === p.theme) return;
      try {
        hapticLight();
        await patchSettings({ theme: nextTheme });
        applyTheme(profile.theme || nextTheme);
        renderSettingsContent();
      } catch (e) {
        tg?.showAlert?.(e.message);
      }
    });
  });

  document.getElementById("toggle-notify")?.addEventListener("click", async () => {
    try {
      if (p.notify) {
        const ok = await tgConfirm("Выключить ежедневное уведомление о смене?");
        if (!ok) return;
        await patchSettings({ notify: false });
      } else {
        const t = document.getElementById("notify-time")?.value?.trim() || p.notify_time;
        if (!t) {
          tg?.showAlert?.("Сначала укажи время");
          return;
        }
        await patchSettings({ notify: true, notify_time: t });
      }
      renderSettingsContent();
    } catch (e) {
      tg?.showAlert?.(e.message);
    }
  });

  document.getElementById("toggle-track")?.addEventListener("click", async () => {
    try {
      await patchSettings({ track_hours: !p.track_hours });
      renderSettingsContent();
      refreshNavBadges();
    } catch (e) {
      tg?.showAlert?.(e.message);
    }
  });

  document.getElementById("toggle-notify-hours")?.addEventListener("click", async () => {
    try {
      await patchSettings({ notify_hours: !p.notify_hours });
      renderSettingsContent();
    } catch (e) {
      tg?.showAlert?.(e.message);
    }
  });

  document.getElementById("save-notify-time")?.addEventListener("click", async () => {
    const t = document.getElementById("notify-time")?.value?.trim();
    if (!t) return;
    try {
      await patchSettings({ notify_time: t });
      renderSettingsContent();
      tg?.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
      tg?.showAlert?.(e.message);
    }
  });
}

async function openSettingsSheet() {
  const sheet = document.getElementById("settings-sheet");
  const content = document.getElementById("settings-content");
  if (!sheet || !content) return;
  if (!profile) profile = await api("/api/me");
  sheet.classList.remove("hidden");
  content.innerHTML = `<div class="loading-wrap">${cardLoaderHtml()}</div>`;
  requestAnimationFrame(() => sheet.classList.add("open"));
  renderSettingsContent();
}

function bindShiftEditRows(root = document) {
  root.querySelectorAll(".shift-row-editable").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest(".shift-delete")) return;
      openHoursSheet(row.dataset.date);
    });
  });
}

async function openHoursSheet(dateStr) {
  if (!profile?.track_hours) {
    renderError("Учёт часов выключен — включи в настройках ⚙");
    return;
  }

  const sheet = document.getElementById("hours-sheet");
  const content = document.getElementById("hours-content");
  sheet.classList.remove("hidden");
  content.innerHTML = `<div class="loading-wrap">${cardLoaderHtml()}</div>`;
  requestAnimationFrame(() => sheet.classList.add("open"));

  try {
    const data = await api(`/api/shifts/day?date=${encodeURIComponent(dateStr)}`);
    const shiftInfo = data.shift_label
      ? `по графику: ${data.shift_label}${data.standard_hours ? `, ${data.standard_hours} ч` : ""}`
      : "смены нет в графике";
    const isEdit = data.logged_hours != null;
    const prefilled = isEdit ? String(data.logged_hours) : "";

    let actions = "";
    if (data.standard_hours) {
      actions += `<button type="button" class="btn btn-primary" id="hours-standard">стандарт · ${data.standard_hours} ч</button>`;
    }
    actions += `
      <input type="number" step="0.5" min="0.5" max="24" class="hours-input" id="hours-custom" value="${prefilled}" placeholder="своё время, напр. 11.5" />
      <button type="button" class="btn btn-primary" id="hours-save">${isEdit ? "обновить" : "сохранить"}</button>
    `;

    content.innerHTML = `
      <div class="hours-title">⏱ ${isEdit ? "редактировать часы" : "внести часы"}</div>
      <div class="hours-meta">${data.weekday} ${data.header}</div>
      <div class="hours-meta">${shiftInfo}</div>
      <div class="hours-actions">${actions}</div>
    `;

    const save = async (hours, isStandard) => {
      await api("/api/shifts", {
        method: "POST",
        body: JSON.stringify({ date: dateStr, hours, is_standard: isStandard }),
      });
      content.innerHTML = `<div class="hours-success">✓ ${isEdit ? "обновлено" : "сохранено"}: ${hours} ч</div>`;
      hapticSuccess();
      await refreshCurrentTab();
      setTimeout(closeHoursSheet, 700);
    };

    const stdBtn = document.getElementById("hours-standard");
    if (stdBtn) {
      stdBtn.onclick = () => save(data.standard_hours, true);
    }
    document.getElementById("hours-save").onclick = () => {
      const val = parseFloat(document.getElementById("hours-custom").value.replace(",", "."));
      if (!val || val <= 0 || val > 24) {
        tg?.showAlert?.("Введи число от 0.5 до 24");
        return;
      }
      save(val, false);
    };
  } catch (e) {
    content.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
}

function fmtMoney(n) {
  if (n == null) return "—";
  return `${Number(n).toLocaleString("ru-RU")} ₽`;
}

function periodIndexOf(periods, p) {
  const i = periods.findIndex(
    (x) => x.year === p.year && x.month === p.month && x.start === p.start && x.end === p.end,
  );
  return i >= 0 ? i : periods.length - 1;
}

async function ensureSalaryPeriods() {
  if (salaryPeriods) return;
  const pr = await api("/api/salary/periods");
  salaryPeriods = pr.periods || [];
  const cur = await api("/api/salary");
  salaryPeriodIndex = salaryPeriods.length
    ? periodIndexOf(salaryPeriods, cur.period)
    : 0;
}

async function ensureComparePeriods() {
  if (comparePeriods) return;
  const pr = await api("/api/salary/periods");
  comparePeriods = pr.periods || [];
  const cur = await api("/api/salary");
  comparePeriodIndex = comparePeriods.length
    ? periodIndexOf(comparePeriods, cur.period)
    : 0;
}

async function renderSalary() {
  renderLoading();
  try {
    await ensureSalaryPeriods();
    const p = salaryPeriods[salaryPeriodIndex];
    const q = p
      ? `?year=${p.year}&month=${p.month}&start=${p.start}&end=${p.end}`
      : "";
    const data = await api(`/api/salary${q}`);
    const periodLabel = data.period.title;

    let mainBlock = "";
    if (data.no_data) {
      mainBlock = `<div class="empty-team">график за период ещё не составлен</div>`;
    } else if (data.track_hours) {
      mainBlock = `
        <div class="salary-table">
          <div class="salary-row head"><span></span><span>график</span><span>внесено</span></div>
          <div class="salary-row"><span>смены</span><span>${data.schedule_shifts}</span><span>${data.actual_shifts}</span></div>
          <div class="salary-row"><span>часы</span><span>${data.schedule_hours}</span><span>${data.actual_hours}</span></div>
          <div class="salary-row"><span>₽</span><span>${fmtMoney(data.approx_salary)}</span><span>${fmtMoney(data.actual_salary)}</span></div>
        </div>
      `;
    } else {
      mainBlock = `
        <div class="salary-simple">
          <div>${data.schedule_shifts} смен · ${data.schedule_hours} ч по графику</div>
          ${data.approx_salary != null ? `<div class="salary-big">${fmtMoney(data.approx_salary)}</div>` : ""}
          ${data.rate ? `<div class="hours-meta">${data.rate} ₽/ч</div>` : `<div class="warn">ставка не указана</div>`}
        </div>
      `;
    }

    const history = (data.history || []).map((h) => {
      const lbl = h.shift_type === "morning" ? "♠" : h.shift_type === "evening" ? "♥" : "";
      const del = data.track_hours
        ? `<button type="button" class="shift-delete" data-date="${h.date}" aria-label="удалить">×</button>`
        : "";
      return `<div class="shift-row shift-row-editable" data-date="${h.date}"><span class="shift-date">${h.date.slice(5)}</span><span class="shift-name">${lbl}</span><span class="shift-status done">${h.hours} ч</span>${del}</div>`;
    }).join("");

    document.getElementById("main").innerHTML = `
      <div class="card-label">${periodLabel}</div>
      ${hoursEntryButtonHtml()}
      <div class="week-nav" style="margin-top:0;margin-bottom:12px">
        <button type="button" class="btn" id="sal-prev" ${salaryPeriodIndex <= 0 ? "disabled" : ""}>←</button>
        <button type="button" class="btn" id="sal-next" ${salaryPeriodIndex >= salaryPeriods.length - 1 ? "disabled" : ""}>→</button>
      </div>
      <div class="card">${mainBlock}</div>
      ${history ? `<div class="card"><div class="card-label">история смен</div><div class="setting-desc" style="margin-bottom:8px">тап — изменить · × — удалить</div>${history}</div>` : ""}
    `;

    document.getElementById("sal-prev")?.addEventListener("click", () => {
      if (salaryPeriodIndex > 0) { salaryPeriodIndex -= 1; renderSalary(); }
    });
    document.getElementById("sal-next")?.addEventListener("click", () => {
      if (salaryPeriodIndex < salaryPeriods.length - 1) { salaryPeriodIndex += 1; renderSalary(); }
    });
    bindHoursEntryButton();
    bindShiftEditRows();

    document.querySelectorAll(".shift-delete").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const date = btn.dataset.date;
        const ok = await tgConfirm(`Удалить смену за ${date.slice(5)}?`);
        if (!ok) return;
        try {
          await api(`/api/shifts?date=${encodeURIComponent(date)}`, { method: "DELETE" });
          hapticSuccess();
          await renderSalary();
          refreshNavBadges();
        } catch (e) {
          tg?.showAlert?.(e.message);
        }
      });
    });
  } catch (e) {
    renderError(e.message);
  }
}

function toggleComparePick(name, role) {
  const idx = comparePick.findIndex((c) => c.name === name);
  if (idx >= 0) {
    comparePick.splice(idx, 1);
    return;
  }
  if (comparePick.length >= 3) {
    tg?.showAlert?.("Максимум 3 коллеги для сравнения");
    return;
  }
  comparePick.push({ name, role });
}

function renderCompareDock() {
  const dock = document.getElementById("compare-dock");
  const app = document.getElementById("app");
  if (!dock) return;

  const show = tab === "people" && peopleScreen === "list" && comparePick.length > 0;
  if (!show) {
    dock.classList.add("hidden");
    dock.setAttribute("aria-hidden", "true");
    app?.classList.remove("has-compare-dock");
    dock.innerHTML = "";
    return;
  }

  const names = comparePick.map((c) => c.name).join(", ");
  const countLabel = comparePick.length === 1 ? "1 коллега" : `${comparePick.length} коллеги`;

  dock.innerHTML = `
    <div class="compare-dock-inner">
      <div class="compare-dock-info">
        <span class="compare-dock-count">${countLabel} для сравнения</span>
        <span class="compare-dock-names">${names}</span>
      </div>
      <button type="button" class="btn btn-primary" id="run-compare-dock">сравнить</button>
    </div>
  `;
  dock.classList.remove("hidden");
  dock.setAttribute("aria-hidden", "false");
  app?.classList.add("has-compare-dock");

  document.getElementById("run-compare-dock")?.addEventListener("click", async () => {
    peopleScreen = "compare";
    renderCompareDock();
    await renderPeople();
  });
}

async function renderPeopleList() {
  renderLoading();
  try {
    const data = await api("/api/colleagues");
    const blocks = data.departments.map((dep) => `
      <div class="role-block">
        <div class="role-title">${escapeHtml(dep.role_label)}</div>
        <div class="people-list">
          ${dep.people.map((p) => {
            const sel = comparePick.some((c) => c.name === p.name);
            return `
              <button type="button" class="person-chip person-chip-btn${sel ? " selected" : ""}" data-name="${escapeAttr(p.name)}" data-role="${escapeAttr(p.role || "")}" data-role-label="${escapeAttr(dep.role_label)}">
                ${escapeHtml(p.name)}
              </button>
            `;
          }).join("")}
        </div>
      </div>
    `).join("");

    document.getElementById("main").innerHTML = `
      <div class="card-label">тап — график · долгий тап — в сравнение · тап по выбранному — убрать</div>
      <div class="card">${blocks || '<div class="empty-team">нет коллег в списке</div>'}</div>
      <p class="quote">everyone's mad here</p>
    `;

    document.querySelectorAll(".person-chip-btn").forEach((btn) => bindPersonChip(btn));
    renderCompareDock();
  } catch (e) {
    renderError(e.message);
  }
}

function rosterDisplayName(entry) {
  const sep = " — ";
  const i = entry.indexOf(sep);
  return i >= 0 ? entry.slice(0, i).trim() : entry.trim();
}

function personChipBtnHtml(name, role, roleLabel) {
  const personName = rosterDisplayName(name);
  return `
    <button type="button" class="person-chip person-chip-btn"
      data-name="${escapeAttr(personName)}"
      data-role="${escapeAttr(role || "")}"
      data-role-label="${escapeAttr(roleLabel || "")}">
      ${escapeHtml(name)}
    </button>
  `;
}

function openColleagueSchedule(name, role, roleLabel, returnTab = null) {
  closeDaySheet();
  colleagueView = {
    name,
    role: role || null,
    role_label: roleLabel || null,
  };
  colleagueWeekOffset = 0;
  colleagueMonthOffset = 0;
  colleagueScheduleMode = "week";
  peopleScreen = "person";
  colleagueReturnTab = returnTab;
  document.getElementById("screen-title").textContent = colleagueView.name;
  hapticLight();
  setTab("people");
}

function bindColleagueChipButtons(root, returnTab = null) {
  if (!root) return;
  root.querySelectorAll(".person-chip-btn[data-name]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openColleagueSchedule(
        btn.dataset.name,
        btn.dataset.role || null,
        btn.dataset.roleLabel || null,
        returnTab,
      );
    });
  });
}

function colleagueBackLabel() {
  if (colleagueReturnTab === "team") return "← на смене";
  if (colleagueReturnTab === "schedule") return "← к графику";
  return "← к списку";
}

function backFromColleagueView() {
  const returnTab = colleagueReturnTab;
  colleagueReturnTab = null;
  if (returnTab && returnTab !== "people") {
    peopleScreen = "list";
    colleagueView = null;
    setTab(returnTab);
    return;
  }
  backToPeopleList();
}

function bindPersonChip(btn) {
  let pressTimer = null;
  let longPressed = false;
  const name = btn.dataset.name;
  const role = btn.dataset.role || null;
  const isSelected = () => comparePick.some((c) => c.name === name);

  const startPress = () => {
    longPressed = false;
    pressTimer = setTimeout(() => {
      longPressed = true;
      if (!isSelected()) toggleComparePick(name, role);
      renderPeopleList();
      hapticLight();
    }, 450);
  };
  const endPress = () => {
    if (pressTimer) clearTimeout(pressTimer);
  };

  btn.addEventListener("touchstart", startPress, { passive: true });
  btn.addEventListener("touchend", endPress);
  btn.addEventListener("touchmove", endPress);
  btn.addEventListener("mousedown", startPress);
  btn.addEventListener("mouseup", endPress);
  btn.addEventListener("mouseleave", endPress);

  btn.addEventListener("click", () => {
    if (longPressed) {
      longPressed = false;
      return;
    }
    if (isSelected()) {
      toggleComparePick(name, role);
      renderPeopleList();
      tg?.HapticFeedback?.selectionChanged();
      return;
    }
    colleagueView = {
      name,
      role,
      role_label: btn.dataset.roleLabel || null,
    };
    colleagueWeekOffset = 0;
    colleagueMonthOffset = 0;
    colleagueScheduleMode = "week";
    peopleScreen = "person";
    colleagueReturnTab = null;
    document.getElementById("screen-title").textContent = colleagueView.name;
    renderPeople();
  });
}

function colleagueScheduleToggleHtml() {
  return `
    <div class="schedule-toggle">
      <button type="button" class="btn${colleagueScheduleMode === "week" ? " active" : ""}" data-col-mode="week">неделя</button>
      <button type="button" class="btn${colleagueScheduleMode === "month" ? " active" : ""}" data-col-mode="month">месяц</button>
    </div>
  `;
}

function bindColleagueScheduleToggle() {
  document.querySelectorAll("[data-col-mode]").forEach((btn) => {
    btn.onclick = () => {
      colleagueScheduleMode = btn.dataset.colMode;
      renderColleagueSchedule();
    };
  });
}

async function renderColleagueSchedule() {
  renderLoading();
  try {
    const c = colleagueView;
    const roleQ = c.role ? `&role=${encodeURIComponent(c.role)}` : "";

    if (colleagueScheduleMode === "month") {
      const data = await api(
        `/api/colleagues/month?name=${encodeURIComponent(c.name)}${roleQ}&offset=${colleagueMonthOffset}`,
      );
      if (data.role_label) colleagueView.role_label = data.role_label;

      const wdHeader = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
        .map((w) => `<div class="month-wd">${w}</div>`).join("");
      let pad = "";
      for (let i = 0; i < data.first_weekday; i += 1) {
        pad += `<div class="month-cell empty" aria-hidden="true"></div>`;
      }
      const cells = data.days.map((d) => monthDayCellHtml(d)).join("");
      const roleLine = colleagueView.role_label
        ? `<div class="card-meta" style="margin-bottom:10px">${escapeHtml(colleagueView.role_label)}</div>`
        : "";

      document.getElementById("main").innerHTML = `
        <button type="button" class="btn back-btn" id="people-back">${colleagueBackLabel()}</button>
        ${roleLine}
        ${colleagueScheduleToggleHtml()}
        <div class="card-label">${data.header}</div>
        <div class="month-legend">
          <span>♠ утро</span><span>♥ вечер</span><span>— вых</span><span>· нет графика</span>
        </div>
        <div class="month-grid">${wdHeader}${pad}${cells}</div>
        <div class="month-stats">
          <span>${data.stats.working} смен</span><span>${data.stats.off} вых</span>
        </div>
        <div class="week-nav">
          <button type="button" class="btn" id="col-month-prev">← пред</button>
          <button type="button" class="btn btn-primary" id="col-month-next">след →</button>
        </div>
      `;

      bindColleagueScheduleToggle();
      bindDayPickers();
      document.getElementById("people-back").onclick = backFromColleagueView;
      document.getElementById("col-month-prev").onclick = () => {
        colleagueMonthOffset -= 1;
        renderColleagueSchedule();
      };
      document.getElementById("col-month-next").onclick = () => {
        colleagueMonthOffset += 1;
        renderColleagueSchedule();
      };
      return;
    }

    const data = await api(
      `/api/colleagues/week?name=${encodeURIComponent(c.name)}${roleQ}&offset=${colleagueWeekOffset}`,
    );
    const daysHtml = data.days.map((d) => weekDayCellHtml(d)).join("");

    if (data.role_label) colleagueView.role_label = data.role_label;
    const roleLine = colleagueView.role_label
      ? `<div class="card-meta" style="margin-bottom:10px">${escapeHtml(colleagueView.role_label)}</div>`
      : "";

    document.getElementById("main").innerHTML = `
      <button type="button" class="btn back-btn" id="people-back">${colleagueBackLabel()}</button>
      ${roleLine}
      ${colleagueScheduleToggleHtml()}
      <div class="card-label">неделя · ${data.header}</div>
      <div class="week-grid">${daysHtml}</div>
      <div class="week-nav">
        <button type="button" class="btn" id="col-prev">← пред</button>
        <button type="button" class="btn btn-primary" id="col-next">след →</button>
      </div>
    `;

    bindColleagueScheduleToggle();
    bindDayPickers();
    document.getElementById("people-back").onclick = backFromColleagueView;
    document.getElementById("col-prev").onclick = () => {
      colleagueWeekOffset -= 1;
      renderColleagueSchedule();
    };
    document.getElementById("col-next").onclick = () => {
      colleagueWeekOffset += 1;
      renderColleagueSchedule();
    };
  } catch (e) {
    renderError(e.message);
  }
}

function backToPeopleList() {
  peopleScreen = "list";
  colleagueView = null;
  colleagueReturnTab = null;
  document.getElementById("screen-title").textContent = TITLES.people;
  updateSubtitle();
  renderPeople();
}

async function renderColleagueWeek() {
  return renderColleagueSchedule();
}

async function renderCompareResult() {
  renderLoading();
  try {
    await ensureComparePeriods();
    const p = comparePeriods[comparePeriodIndex];
    const data = await api("/api/colleagues/compare", {
      method: "POST",
      body: JSON.stringify({
        colleagues: comparePick,
        year: p.year,
        month: p.month,
        start: p.start,
        end: p.end,
      }),
    });

    const workRows = (data.common_work || []).map((w) => {
      const parts = Object.entries(w.shifts).map(([n, s]) => `${n}: ${s}`).join(" · ");
      return `<div class="shift-row"><span class="shift-date">${w.day}</span><span class="shift-name">${parts}</span></div>`;
    }).join("") || `<div class="empty-team">общих рабочих дней нет</div>`;

    const offRows = (data.common_off || []).map((d) =>
      `<span class="person-chip">${d.date}</span>`,
    ).join("") || `<span class="hours-meta">общих выходных нет</span>`;

    const names = data.participants.map((p) => p.name).join(", ");

    document.getElementById("main").innerHTML = `
      <button type="button" class="btn back-btn" id="compare-back">← к списку</button>
      <div class="card">
        <div class="card-label">${data.period.label}</div>
        <div class="card-meta">${names}</div>
      </div>
      <div class="week-nav" style="margin-top:0;margin-bottom:12px">
        <button type="button" class="btn" id="cmp-prev" ${comparePeriodIndex <= 0 ? "disabled" : ""}>←</button>
        <button type="button" class="btn" id="cmp-next" ${comparePeriodIndex >= comparePeriods.length - 1 ? "disabled" : ""}>→</button>
      </div>
      <div class="card">
        <div class="card-label">вместе на смене</div>
        ${workRows}
      </div>
      <div class="card">
        <div class="card-label">вместе отдыхают</div>
        <div class="people-list" style="margin-top:8px">${offRows}</div>
      </div>
    `;

    document.getElementById("compare-back").onclick = () => {
      peopleScreen = "list";
      document.getElementById("screen-title").textContent = TITLES.people;
      updateSubtitle();
      renderPeople();
    };
    document.getElementById("cmp-prev")?.addEventListener("click", () => {
      if (comparePeriodIndex > 0) { comparePeriodIndex -= 1; renderCompareResult(); }
    });
    document.getElementById("cmp-next")?.addEventListener("click", () => {
      if (comparePeriodIndex < comparePeriods.length - 1) { comparePeriodIndex += 1; renderCompareResult(); }
    });
  } catch (e) {
    renderError(e.message);
  }
}

function renderPeople() {
  if (peopleScreen === "person") return renderColleagueSchedule();
  if (peopleScreen === "compare") return renderCompareResult();
  return renderPeopleList();
}

document.getElementById("hours-backdrop")?.addEventListener("click", closeHoursSheet);
document.getElementById("settings-backdrop")?.addEventListener("click", closeSettingsSheet);
document.getElementById("day-backdrop")?.addEventListener("click", closeDaySheet);
document.getElementById("open-settings")?.addEventListener("click", () => {
  hapticLight();
  openSettingsSheet();
});

setupSheetSwipe("day-sheet", closeDaySheet);
setupSheetSwipe("hours-sheet", closeHoursSheet);
setupSheetSwipe("settings-sheet", closeSettingsSheet);

function setupPullRefresh() {
  const main = document.getElementById("main");
  if (!main) return;
  let startY = 0;
  let pulling = false;
  let pullDist = 0;

  main.addEventListener("touchstart", (e) => {
    if (tab !== "schedule" || main.scrollTop > 4) return;
    startY = e.touches[0].clientY;
    pulling = true;
    pullDist = 0;
  }, { passive: true });

  main.addEventListener("touchmove", (e) => {
    if (!pulling) return;
    pullDist = Math.max(0, e.touches[0].clientY - startY);
    if (pullDist > 0 && pullDist < 120) {
      main.style.transform = `translateY(${pullDist * 0.22}px)`;
    }
  }, { passive: true });

  const end = async () => {
    if (!pulling) return;
    pulling = false;
    main.style.transform = "";
    if (tab === "schedule" && pullDist > 72) {
      hapticLight();
      await renderSchedule();
      await refreshNavBadges();
    }
    pullDist = 0;
  };
  main.addEventListener("touchend", end);
  main.addEventListener("touchcancel", end);
}

setupPullRefresh();

function updateSubtitle() {
  const el = document.getElementById("screen-subtitle");
  if (tab === "schedule") el.textContent = pickScheduleWhisper();
  else el.textContent = SUBTITLES[tab] || "";
}

function setTab(next) {
  const main = document.getElementById("main");
  if (tab === next && next === "people" && peopleScreen !== "list") {
    hapticLight();
    backToPeopleList();
    return;
  }

  const changed = tab !== next;
  if (changed) hapticLight();
  if (changed && main) main.classList.add("tab-fade");

  tab = next;
  if (tab !== "people") {
    peopleScreen = "list";
    colleagueView = null;
    colleagueReturnTab = null;
    renderCompareDock();
  }
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.getElementById("screen-title").textContent = TITLES[tab];
  updateSubtitle();

  const finishFade = () => main?.classList.remove("tab-fade");

  if (tab === "schedule") renderSchedule().finally(finishFade);
  else if (tab === "team") renderTeam().finally(finishFade);
  else if (tab === "people") { renderPeople(); finishFade(); }
  else if (tab === "salary") renderSalary().finally(finishFade);
  else renderAnalytics().finally(finishFade);
  if (tab === "people") renderCompareDock();
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => setTab(btn.dataset.tab));
});

(async () => {
  try {
    const start = parseStartParams();
    const ok = await loadProfile();
    hideSplash();
    if (!ok) return;

    if (start.view === "team") {
      teamDayOffset = start.teamOffset;
      setTab("team");
    } else if (start.view === "hours" && start.hoursDate) {
      setTab("schedule");
      await openHoursSheet(start.hoursDate);
    } else if (start.view === "settings") {
      setTab("schedule");
      await openSettingsSheet();
    } else {
      setTab("schedule");
    }
  } catch (e) {
    hideSplash();
    renderError(e.message);
  }
})();
