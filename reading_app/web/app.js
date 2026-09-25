const RED = "#d00000";
const INK = "#111111";

const VIEWS = [
  ["leer", "Leer"],
  ["hoy", "Programa de hoy"],
  ["progreso", "Progreso"],
  ["historial", "Historial"],
  ["sets", "Gestionar sets"],
  ["ajustes", "Ajustes"],
];

const ui = {
  view: "leer",
  error: "",
  message: "",
  database: "",
  read: { phase: "idle", session: null, index: 0 },
  selectedWords: [],
  wordFilter: "",
};

const app = document.querySelector("#app");

document.addEventListener("keydown", (event) => {
  if (ui.view !== "leer" || ui.read.phase !== "presenting") return;
  if (event.target.matches("input, textarea, select")) return;
  if (event.key === "ArrowRight" || event.key === " ") {
    event.preventDefault();
    record("exposure");
  }
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function charsOf(word) {
  return Array.from(word);
}

function applyCase(word, mode) {
  if (mode === "mayusculas") return word.toLocaleUpperCase("es");
  if (mode === "minusculas") return word.toLocaleLowerCase("es");
  return word;
}

function middleIndex(word) {
  const chars = charsOf(word);
  if (!chars.length) return 0;
  return Math.floor((chars.length - 1) / 2);
}

function fontSize(word) {
  const length = charsOf(word).length;
  if (length <= 5) return 150;
  if (length <= 8) return 124;
  return 100;
}

function wordHtml(word, displayMode, caseMode) {
  const shown = applyCase(word, caseMode);
  const chars = charsOf(shown);
  const center = middleIndex(shown);
  if (displayMode === "central_letter") {
    return chars
      .map((char, index) => {
        const color = index === center ? RED : INK;
        return `<span style="color:${color}">${escapeHtml(char)}</span>`;
      })
      .join("");
  }
  const color = displayMode === "black" ? INK : RED;
  return `<span style="color:${color}">${escapeHtml(shown)}</span>`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "No se pudo completar");
  }
  return data;
}

function showError(error) {
  ui.error = error.message || String(error);
  render();
}

async function go(view) {
  ui.view = view;
  ui.error = "";
  ui.message = "";
  if (view !== "leer") ui.selectedWords = [];
  await render();
}

async function render() {
  if (ui.view === "leer") {
    app.innerHTML = readView();
    bindRead();
    return;
  }
  app.innerHTML = `<div class="shell"><nav class="nav" id="nav"></nav><main class="main" id="main"><p>Cargando…</p></main></div>`;
  document.querySelector("#nav").innerHTML = navHtml();
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => go(button.dataset.view));
  });
  const main = document.querySelector("#main");
  try {
    if (ui.view === "hoy") main.innerHTML = await todayHtml();
    else if (ui.view === "progreso") main.innerHTML = await progressHtml();
    else if (ui.view === "historial") main.innerHTML = await historyHtml();
    else if (ui.view === "sets") main.innerHTML = await setsHtml();
    else main.innerHTML = await settingsHtml();
    bindMain();
  } catch (error) {
    main.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

function navHtml() {
  const links = VIEWS.map(
    ([id, label]) =>
      `<button type="button" data-view="${id}" class="${id === ui.view ? "active" : ""}">${label}</button>`,
  ).join("");
  return `<p>${escapeHtml(ui.database || "")}</p>${links}`;
}

function banner(text) {
  return ui.error ? `<p class="error">${escapeHtml(ui.error)}</p>` : "";
}

function note(text) {
  return ui.message ? `<p class="ok">${escapeHtml(ui.message)}</p>` : "";
}

function readView() {
  const phase = ui.read.phase;
  let stage = "";
  let actions = "";
  if (phase === "presenting" && ui.read.session) {
    const session = ui.read.session;
    const word = session.words[ui.read.index];
    const size = fontSize(applyCase(word.word, session.case_mode));
    stage = `
      <div class="stage">
        <p class="word" style="font-size:${size}px">${wordHtml(word.word, session.display_mode, session.case_mode)}</p>
        <p class="progress">${ui.read.index + 1} / ${session.words.length}</p>
      </div>
      ${session.presentation_mode === "presentacion" ? '<p class="mode-note">Modo presentación. → muestra la palabra y no evalúa.</p>' : ""}
      <div class="actions">
        <button type="button" data-result="correct">✓ Correcta</button>
        <button type="button" data-result="exposure">→ Mostrar / Sin evaluar</button>
        <button type="button" data-result="incorrect">✗ Reforzar</button>
      </div>`;
  } else if (phase === "completed") {
    stage = `<div class="stage"><h1 class="done-title">Set completado</h1></div>`;
    actions = `
      <div class="actions">
        <button type="button" data-read="repeat">Presentar de nuevo</button>
        <button type="button" data-read="next">Siguiente set</button>
        <button type="button" data-read="home">Volver</button>
      </div>`;
  } else {
    stage = `
      <div class="stage">
        <button type="button" class="btn primary" data-read="start">Presentar siguiente set</button>
      </div>`;
  }
  return `
    <section class="read">
      <button type="button" class="adult-link" data-view="hoy">Adulto</button>
      ${banner()}
      ${stage}
      ${actions}
    </section>`;
}

function bindRead() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => go(button.dataset.view));
  });
  document.querySelectorAll("[data-result]").forEach((button) => {
    button.addEventListener("click", () => record(button.dataset.result));
  });
  document.querySelector("[data-read='start']")?.addEventListener("click", () => startSession({ kind: "next" }));
  document.querySelector("[data-read='next']")?.addEventListener("click", () => {
    const current = ui.read.session;
    startSession({ kind: "next", exclude_set_id: current ? current.set_id : null });
  });
  document.querySelector("[data-read='repeat']")?.addEventListener("click", () => {
    const current = ui.read.session;
    if (!current) return;
    startSession({ kind: "repeat", set_id: current.set_id, session_type: current.session_type });
  });
  document.querySelector("[data-read='home']")?.addEventListener("click", () => {
    ui.read = { phase: "idle", session: null, index: 0 };
    ui.error = "";
    render();
  });
}

async function startSession(body) {
  ui.error = "";
  try {
    const session = await api("/api/sessions", { method: "POST", body: JSON.stringify(body) });
    ui.read = { phase: "presenting", session, index: 0 };
    ui.view = "leer";
    render();
  } catch (error) {
    showError(error);
  }
}

async function record(result) {
  const session = ui.read.session;
  if (!session || ui.read.phase !== "presenting") return;
  const word = session.words[ui.read.index];
  const last = ui.read.index + 1 >= session.words.length;
  try {
    await api(`/api/sessions/${session.session_id}/present`, {
      method: "POST",
      body: JSON.stringify({
        word_id: word.id,
        set_id: session.set_id,
        result,
        complete: last,
      }),
    });
    if (last) ui.read.phase = "completed";
    else ui.read.index += 1;
    ui.error = "";
    render();
  } catch (error) {
    showError(error);
  }
}

async function todayHtml() {
  const data = await api("/api/today");
  todayWords = data.manual_words;
  const suggestion = data.suggest_advance
    ? `<div class="banner">La fecha del calendario ha cambiado. El día del programa no avanza solo.
        <div class="row">
          <button type="button" class="btn" data-action="advance">Avanzar al día siguiente</button>
          <button type="button" class="btn" data-action="dismiss">Hoy no</button>
        </div>
      </div>`
    : "";
  const sets = data.sets.length
    ? data.sets.map((set) => `
        <article class="card">
          <h3>${set.seen_today ? "✓" : "○"} ${escapeHtml(set.name)} · ${set.today}</h3>
          <p class="words">${escapeHtml(set.words.join(", "))}</p>
          <p class="hint">Presentaciones hoy: ${set.today} · Presentaciones totales: ${set.total}</p>
          ${set.eligible ? `<p class="banner warn">«${escapeHtml(set.name)}» ha alcanzado el criterio de retirada.</p>
            <button type="button" class="btn" data-retire="${set.id}">Retirar set</button>` : ""}
          <div class="row"><button type="button" class="btn" data-present="${set.id}">Presentar este set</button></div>
        </article>`).join("")
    : `<p class="empty">No hay sets activos.</p>`;
  const reinforcement = data.reinforcement.length
    ? `${data.reinforcement.map((item) => `<p>${escapeHtml(item.word)} · ${item.incorrect_count} incorrectas</p>`).join("")}
       <button type="button" class="btn" data-action="reinforce">Sesión de refuerzo</button>`
    : `<p class="hint">No hay palabras con dificultades repetidas.</p>`;
  const setOptions = data.manual_sets
    .map((set) => `<option value="${set.id}">${escapeHtml(set.name)}</option>`)
    .join("");
  return `
    ${banner()}
    <h1>Programa de hoy</h1>
    ${suggestion}
    <p class="lede">Día del programa: ${data.programme_day}</p>
    <div class="metrics">
      <div class="metric"><span>Sets activos</span><strong>${data.active_sets}</strong></div>
      <div class="metric"><span>Palabras activas</span><strong>${data.active_words}</strong></div>
    </div>
    <button type="button" class="btn" data-action="advance">Avanzar al día siguiente</button>
    <h2>Sets</h2>
    ${sets}
    <h2>Refuerzo</h2>
    ${reinforcement}
    <h2>Presentación libre</h2>
    <p class="hint">No cambia el turno de los sets. Por defecto no cuenta para la retirada automática.</p>
    <label>Set
      <select id="manual-set">${setOptions}</select>
    </label>
    <div class="row"><button type="button" class="btn" data-action="manual-set">Presentar set elegido</button></div>
    <label>Buscar palabra
      <input id="word-filter" type="text" value="${escapeHtml(ui.wordFilter)}">
    </label>
    <div class="picker" id="word-picker"></div>
    <div class="chips" id="word-chips"></div>
    <button type="button" class="btn" data-action="manual-words">Presentar palabras elegidas</button>
  `;
}

function bindMain() {
  document.querySelectorAll("[data-action='advance']").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api("/api/programme/advance", { method: "POST" });
        ui.message = "Día del programa avanzado.";
        await render();
      } catch (error) {
        showError(error);
      }
    });
  });
  document.querySelector("[data-action='dismiss']")?.addEventListener("click", async () => {
    await api("/api/programme/dismiss-suggestion", { method: "POST" });
    await render();
  });
  document.querySelectorAll("[data-retire]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/sets/${button.dataset.retire}/retire`, { method: "POST" });
        await render();
      } catch (error) {
        showError(error);
      }
    });
  });
  document.querySelectorAll("[data-present]").forEach((button) => {
    button.addEventListener("click", () => startSession({ kind: "set", set_id: Number(button.dataset.present), session_type: "normal" }));
  });
  document.querySelector("[data-action='reinforce']")?.addEventListener("click", () => startSession({ kind: "reinforcement" }));
  document.querySelector("[data-action='manual-set']")?.addEventListener("click", () => {
    const select = document.querySelector("#manual-set");
    startSession({ kind: "set", set_id: Number(select.value), session_type: "manual" });
  });
  const filter = document.querySelector("#word-filter");
  if (filter) {
    paintWordPicker();
    filter.addEventListener("input", () => {
      ui.wordFilter = filter.value;
      paintWordPicker();
    });
  }
  document.querySelector("[data-action='manual-words']")?.addEventListener("click", () => {
    if (!ui.selectedWords.length) {
      ui.error = "Elige al menos una palabra.";
      render();
      return;
    }
    startSession({ kind: "words", word_ids: ui.selectedWords.map((item) => item.id) });
  });
  document.querySelectorAll("[data-rename]").forEach((button) => {
    button.addEventListener("click", async () => {
      const input = document.querySelector(`#name-${button.dataset.rename}`);
      try {
        await api(`/api/sets/${button.dataset.rename}/rename`, {
          method: "POST",
          body: JSON.stringify({ name: input.value }),
        });
        await render();
      } catch (error) {
        showError(error);
      }
    });
  });
  document.querySelectorAll("[data-activate]").forEach((button) => {
    button.addEventListener("click", () => postSet(button.dataset.activate, "activate"));
  });
  document.querySelectorAll("[data-set-retire]").forEach((button) => {
    button.addEventListener("click", () => postSet(button.dataset.setRetire, "retire"));
  });
  document.querySelectorAll("[data-move]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/sets/${button.dataset.move}/move`, {
          method: "POST",
          body: JSON.stringify({ direction: Number(button.dataset.direction) }),
        });
        await render();
      } catch (error) {
        showError(error);
      }
    });
  });
  document.querySelector("#create-set")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const needed = Number(form.dataset.count);
    if (ui.selectedWords.length !== needed) {
      ui.error = `Elige exactamente ${needed} palabras.`;
      await render();
      return;
    }
    try {
      await api("/api/sets", {
        method: "POST",
        body: JSON.stringify({
          name: form.querySelector("#new-set-name").value,
          word_ids: ui.selectedWords.map((item) => item.id),
        }),
      });
      ui.selectedWords = [];
      ui.message = "Set creado.";
      await render();
    } catch (error) {
      showError(error);
    }
  });
  document.querySelector("#settings-form")?.addEventListener("submit", saveSettings);
  document.querySelector("[data-action='sync']")?.addEventListener("click", async () => {
    try {
      const result = await api("/api/vocabulary/sync", { method: "POST" });
      ui.message = `Vocabulario sincronizado (${result.count} palabras leídas).`;
      await render();
    } catch (error) {
      showError(error);
    }
  });
  document.querySelector("[data-action='use-db']")?.addEventListener("click", async () => {
    const name = document.querySelector("#active-db").value;
    try {
      await api("/api/databases/active", { method: "POST", body: JSON.stringify({ name }) });
      ui.read = { phase: "idle", session: null, index: 0 };
      ui.database = name;
      ui.message = `Base activa: ${name}`;
      await render();
    } catch (error) {
      showError(error);
    }
  });
  document.querySelector("[data-action='create-db']")?.addEventListener("click", async () => {
    const name = document.querySelector("#new-db").value;
    try {
      const result = await api("/api/databases", { method: "POST", body: JSON.stringify({ name }) });
      ui.read = { phase: "idle", session: null, index: 0 };
      ui.database = result.active;
      ui.message = `Creada y activa: ${result.active}`;
      await render();
    } catch (error) {
      showError(error);
    }
  });
  document.querySelector("[data-action='backup']")?.addEventListener("click", async () => {
    try {
      const result = await api("/api/databases/backup", { method: "POST" });
      ui.message = `Copia guardada en ${result.path}`;
      await render();
    } catch (error) {
      showError(error);
    }
  });
  document.querySelector("[data-action='reset']")?.addEventListener("click", () => confirmAction("/api/databases/reset", "#reset-text", "El programa vuelve al día 1."));
  document.querySelector("[data-action='recreate']")?.addEventListener("click", () => confirmAction("/api/databases/recreate", "#recreate-text", "Base recreada en el día 1."));
  document.querySelector("[data-action='delete-db']")?.addEventListener("click", async () => {
    const name = document.querySelector("#delete-db").value;
    const confirmation = document.querySelector("#delete-text").value;
    try {
      const result = await api("/api/databases/delete", {
        method: "POST",
        body: JSON.stringify({ name, confirmation }),
      });
      ui.database = result.active;
      ui.message = `Movida a ${result.path}`;
      await render();
    } catch (error) {
      showError(error);
    }
  });
}

async function postSet(id, action) {
  try {
    await api(`/api/sets/${id}/${action}`, { method: "POST" });
    await render();
  } catch (error) {
    showError(error);
  }
}

async function confirmAction(path, field, message) {
  const confirmation = document.querySelector(field).value;
  try {
    await api(path, { method: "POST", body: JSON.stringify({ confirmation }) });
    ui.read = { phase: "idle", session: null, index: 0 };
    ui.message = message;
    await render();
  } catch (error) {
    showError(error);
  }
}

let todayWords = [];

function paintWordPicker() {
  const picker = document.querySelector("#word-picker");
  if (!picker) return;
  const query = ui.wordFilter.trim().toLocaleLowerCase("es");
  const matches = todayWords.filter((word) => word.word.toLocaleLowerCase("es").includes(query)).slice(0, 40);
  picker.innerHTML = matches
    .map((word) => {
      const checked = ui.selectedWords.some((item) => item.id === word.id) ? "checked" : "";
      const category = word.category ? ` (${escapeHtml(word.category)})` : "";
      return `<label class="check"><input type="checkbox" data-word="${word.id}" ${checked}> ${escapeHtml(word.word)}${category}</label>`;
    })
    .join("");
  picker.querySelectorAll("[data-word]").forEach((input) => {
    input.addEventListener("change", () => {
      const id = Number(input.dataset.word);
      const word = todayWords.find((item) => item.id === id);
      if (input.checked) {
        if (!ui.selectedWords.some((item) => item.id === id)) ui.selectedWords.push(word);
      } else {
        ui.selectedWords = ui.selectedWords.filter((item) => item.id !== id);
      }
      paintChips();
    });
  });
  paintChips();
}

function paintChips() {
  const chips = document.querySelector("#word-chips");
  if (!chips) return;
  chips.innerHTML = ui.selectedWords.map((word) => `<span>${escapeHtml(word.word)}</span>`).join("");
}

async function progressHtml() {
  const data = await api("/api/progress");
  const summary = data.summary;
  const metrics = [
    ["Día del programa", summary.programme_day],
    ["Presentaciones", summary.total_presentations],
    ["Exposiciones", summary.neutral_exposures],
    ["Lecturas evaluadas", summary.evaluated_readings],
    ["Correctas", summary.correct_readings],
    ["Incorrectas", summary.incorrect_readings],
    ["Palabras activas", summary.active_words],
    ["Palabras retiradas", summary.retired_words],
    ["Sets activos", summary.active_sets],
    ["Sets retirados", summary.retired_sets],
  ]
    .map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
  return `
    <h1>Progreso</h1>
    <div class="metrics">${metrics}</div>
    <p class="hint">La precisión usa solo lecturas evaluadas. Las exposiciones con → no la modifican.</p>
    ${tableHtml(data.words)}
  `;
}

function tableHtml(rows) {
  if (!rows.length) return `<p class="empty">Todavía no hay datos.</p>`;
  const columns = Object.keys(rows[0]);
  const head = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column] ?? "")}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

async function historyHtml() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const query = params.toString();
  const data = await api(`/api/history${query ? `?${query}` : ""}`);
  const dateOn = params.has("calendar_date");
  const lines = data.rows
    .map(
      (row) => `<article class="card">
        <h3>${escapeHtml(row.Fecha)} · ${escapeHtml(row.Set)} · día ${row["Día del programa"]}</h3>
        <p>${row.Sesiones} sesiones · ${row.Presentaciones} presentaciones · ${row.Exposiciones} exposiciones · ${row.Correctas} correctas · ${row.Incorrectas} incorrectas</p>
      </article>`,
    )
    .join("");
  return `
    <h1>Historial</h1>
    <form id="history-form" class="filters">
      <label class="check"><input id="use-date" type="checkbox" ${dateOn ? "checked" : ""}> Filtrar por fecha</label>
      <label>Fecha <input id="history-date" type="date" value="${escapeHtml(params.get("calendar_date") || "")}"></label>
      <label>Día del programa
        <select id="history-day">
          <option value="">Todos</option>
          ${data.days.map((day) => `<option value="${day}" ${String(day) === params.get("programme_day") ? "selected" : ""}>${day}</option>`).join("")}
        </select>
      </label>
      <label>Set
        <select id="history-set">
          <option value="">Todos</option>
          ${data.sets.map((set) => `<option value="${set.id}" ${String(set.id) === params.get("set_id") ? "selected" : ""}>${escapeHtml(set.name)} (${escapeHtml(set.state)})</option>`).join("")}
        </select>
      </label>
      <label>Palabra
        <select id="history-word">
          <option value="">Todas</option>
          ${data.words.map((word) => `<option value="${word.id}" ${String(word.id) === params.get("word_id") ? "selected" : ""}>${escapeHtml(word.word)}</option>`).join("")}
        </select>
      </label>
      <button type="submit" class="btn">Ver</button>
    </form>
    ${lines || `<p class="empty">No hay presentaciones con ese filtro.</p>`}
    ${tableHtml(data.rows)}
  `;
}

async function setsHtml() {
  const data = await api("/api/sets");
  todayWords = data.available;
  const cards = data.sets
    .map((set) => `
      <article class="card">
        <h3>${escapeHtml(set.name)} · ${escapeHtml(set.state_label)}</h3>
        <p class="words">${escapeHtml(set.words.join(", "))}</p>
        <p class="hint">Presentaciones hoy: ${set.today} · Presentaciones totales: ${set.total}</p>
        <label>Nombre <input id="name-${set.id}" type="text" value="${escapeHtml(set.name)}"></label>
        <div class="row">
          <button type="button" class="btn" data-rename="${set.id}">Guardar nombre</button>
          ${set.state === "PLANNED" ? `
            <button type="button" class="btn" data-activate="${set.id}">Activar</button>
            <button type="button" class="btn" data-move="${set.id}" data-direction="-1">Subir</button>
            <button type="button" class="btn" data-move="${set.id}" data-direction="1">Bajar</button>` : ""}
          ${set.state === "ACTIVE" || set.state === "PLANNED" ? `<button type="button" class="btn" data-set-retire="${set.id}">Retirar set</button>` : ""}
        </div>
      </article>`)
    .join("");
  return `
    ${banner()}${note()}
    <h1>Gestionar sets</h1>
    <p class="hint">Cada set nuevo usa ${data.words_per_set} palabras. Una palabra no puede estar en dos sets abiertos.</p>
    ${cards}
    <h2>Crear set</h2>
    ${
      data.available.length < data.words_per_set
        ? `<p class="empty">No hay bastantes palabras libres para un set nuevo.</p>`
        : `<form id="create-set" data-count="${data.words_per_set}">
            <label>Nombre del set <input id="new-set-name" type="text" required></label>
            <label>Buscar palabra <input id="word-filter" type="text" value="${escapeHtml(ui.wordFilter)}"></label>
            <div class="picker" id="word-picker"></div>
            <div class="chips" id="word-chips"></div>
            <button type="submit" class="btn primary">Crear set</button>
          </form>`
    }
  `;
}

async function settingsHtml() {
  const data = await api("/api/settings");
  const state = data.state;
  ui.database = data.active;
  const options = (pairs, current) =>
    pairs.map(([value, label]) => `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`).join("");
  const databases = data.databases
    .map((name) => `<option value="${escapeHtml(name)}" ${name === data.active ? "selected" : ""}>${escapeHtml(name)}</option>`)
    .join("");
  const others = data.databases.filter((name) => name !== data.active);
  const suggestion = state.suggest_advance
    ? `<div class="banner">La fecha del calendario ha cambiado. El día del programa no avanza solo.
        <div class="row">
          <button type="button" class="btn" data-action="advance">Avanzar al día siguiente</button>
          <button type="button" class="btn" data-action="dismiss">Hoy no</button>
        </div>
      </div>`
    : "";
  return `
    ${banner()}${note()}
    <h1>Ajustes</h1>
    ${suggestion}
    <form id="settings-form">
      <h2>Pantalla</h2>
      <div class="form-grid">
        <label>Modo visual
          <select name="display_mode">${options([["doman_red", "Doman / palabra en rojo"], ["central_letter", "Letra central en rojo"], ["black", "Negro"]], state.display_mode)}</select>
        </label>
        <label>Mayúsculas
          <select name="case_mode">${options([["mayusculas", "Mayúsculas"], ["minusculas", "Minúsculas"], ["original", "Como está escrito"]], state.case_mode)}</select>
        </label>
        <label>Modo de sesión
          <select name="presentation_mode">${options([["presentacion", "Modo presentación"], ["seguimiento", "Modo seguimiento"]], state.presentation_mode)}</select>
        </label>
      </div>
      <label class="check"><input name="shuffle_within_set" type="checkbox" ${state.shuffle_within_set ? "checked" : ""}> Mezclar el orden dentro del set</label>
      <h2>Programa</h2>
      <div class="form-grid">
        <label>Palabras por set <input name="words_per_set" type="number" min="3" max="8" value="${state.words_per_set}"></label>
        <label>Máximo de sets activos <input name="max_active_sets" type="number" min="1" max="10" value="${state.max_active_sets}"></label>
        <label>Fuente de nuevas palabras
          <select name="vocabulary_source">${options([["mis_palabras", "Mis palabras"], ["frecuencia", "Frecuencia"], ["ambas", "Ambas"]], state.vocabulary_source)}</select>
        </label>
        <label>Exposiciones para poder retirar <input name="retirement_exposure_target" type="number" min="1" max="200" value="${state.retirement_exposure_target}"></label>
        <label>Días en el programa para poder retirar <input name="retirement_min_days" type="number" min="1" max="60" value="${state.retirement_min_days}"></label>
      </div>
      <label class="check"><input name="auto_retire" type="checkbox" ${state.auto_retire ? "checked" : ""}> Retirada automática</label>
      <p class="hint">Si está apagada, el programa avisa y espera a que pulses Retirar set. Si está encendida, sustituye los sets al avanzar el día.</p>
      <label class="check"><input name="manual_counts_toward_retirement" type="checkbox" ${state.manual_counts_toward_retirement ? "checked" : ""}> La presentación libre cuenta para la retirada</label>
      <div class="row"><button type="submit" class="btn primary">Guardar ajustes</button></div>
    </form>
    <div class="row">
      <button type="button" class="btn" data-action="advance">Avanzar al día siguiente del programa</button>
      <button type="button" class="btn" data-action="sync">Sincronizar vocabulario Excel</button>
    </div>
    <h2>Base de datos / Perfil</h2>
    <label>Base de datos activa <select id="active-db">${databases}</select></label>
    <div class="row"><button type="button" class="btn" data-action="use-db">Usar esta base</button></div>
    <label>Crear nueva base de datos <input id="new-db" type="text" placeholder="lectura_octubre"></label>
    <div class="row">
      <button type="button" class="btn" data-action="create-db">Crear nueva base de datos</button>
      <button type="button" class="btn" data-action="backup">Crear copia de seguridad</button>
    </div>
    <div class="danger">
      <h2>Acciones irreversibles</h2>
      <p class="hint">Restablecer progreso borra sesiones, presentaciones y sets de esta base. Los Excel no se tocan.</p>
      <label>Escribe REINICIAR para restablecer <input id="reset-text" type="text"></label>
      <button type="button" class="btn" data-action="reset">Restablecer progreso</button>
      <p class="hint">Recrear hace primero una copia, luego crea el esquema de nuevo y sincroniza el Excel.</p>
      <label>Escribe RECREAR para recrear <input id="recreate-text" type="text"></label>
      <button type="button" class="btn" data-action="recreate">Recrear base de datos</button>
      ${
        others.length
          ? `<label>Base a retirar <select id="delete-db">${others.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}</select></label>
             <label>Escribe el nombre del archivo para confirmar <input id="delete-text" type="text"></label>
             <button type="button" class="btn" data-action="delete-db">Mover base a copias</button>`
          : ""
      }
    </div>
  `;
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    display_mode: form.display_mode.value,
    case_mode: form.case_mode.value,
    presentation_mode: form.presentation_mode.value,
    shuffle_within_set: form.shuffle_within_set.checked,
    words_per_set: Number(form.words_per_set.value),
    max_active_sets: Number(form.max_active_sets.value),
    vocabulary_source: form.vocabulary_source.value,
    retirement_exposure_target: Number(form.retirement_exposure_target.value),
    retirement_min_days: Number(form.retirement_min_days.value),
    auto_retire: form.auto_retire.checked,
    manual_counts_toward_retirement: form.manual_counts_toward_retirement.checked,
  };
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    ui.message = "Ajustes guardados.";
    await render();
  } catch (error) {
    showError(error);
  }
}

document.addEventListener("submit", (event) => {
  if (event.target.id !== "history-form") return;
  event.preventDefault();
  const params = new URLSearchParams();
  if (document.querySelector("#use-date").checked) {
    const date = document.querySelector("#history-date").value;
    if (date) params.set("calendar_date", date);
  }
  const day = document.querySelector("#history-day").value;
  const setId = document.querySelector("#history-set").value;
  const wordId = document.querySelector("#history-word").value;
  if (day) params.set("programme_day", day);
  if (setId) params.set("set_id", setId);
  if (wordId) params.set("word_id", wordId);
  window.location.hash = params.toString();
  render();
});

async function boot() {
  try {
    const data = await api("/api/bootstrap");
    ui.database = data.database;
  } catch (error) {
    ui.error = error.message;
  }
  await render();
}

boot();
