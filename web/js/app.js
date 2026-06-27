'use strict';

/* ═══════════════════ STATE ═══════════════════ */
const S = {
  catalog: null,       // { artifacts, containers, armors, stat_defs }
  inventory: null,     // { artifact_ids, container_ids, armor_ids }
  build: {
    armorId:     null,
    containerId: null,
    slots:       [],   // array of artifact ids (or null)
    maxHp:       100,
    mode:        'avg',
  },
  picker: {
    slot:      -1,
    filter:    'all',
    search:    '',
  },
  opt: {
    presets:   [],
    weights:   {},
    activePreset: null,
  },
};

/* ═══════════════════ API ═══════════════════ */
const api = {
  async get(url) {
    const r = await fetch(url);
    const data = await r.json();
    if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), { status: r.status, data });
    return data;
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), { status: r.status, data });
    return data;
  },
};

/* ═══════════════════ INIT ═══════════════════ */
document.addEventListener('DOMContentLoaded', async () => {
  try {
    setLoadingText('Загрузка данных...');

    // Check auth first
    const status = await api.get('/api/status').catch(() => null);
    if (!status || !status.user) {
      window.location.href = '/login';
      return;
    }

    // Show user menu
    const menu = document.getElementById('user-menu');
    menu.style.display = 'flex';
    document.getElementById('user-name').textContent = status.user.username;
    if (status.user.is_admin) {
      document.getElementById('admin-link').style.display = '';
    }

    // Load catalog with retry — server may still be downloading it from GitHub on first start
    let catalog = null;
    for (let attempt = 1; attempt <= 12; attempt++) {
      try {
        catalog = await api.get('/api/catalog');
        break;
      } catch (e) {
        if (e.status === 503) {
          setLoadingText(`Загрузка базы данных с GitHub... (${attempt * 5}с)`);
          await new Promise(r => setTimeout(r, 5000));
        } else {
          throw e;
        }
      }
    }
    if (!catalog) throw new Error('Каталог не загрузился за 60 секунд');

    setLoadingText('Загрузка инвентаря...');
    const [inventory, presets] = await Promise.all([
      api.get('/api/inventory'),
      api.get('/api/presets'),
    ]);
    S.catalog     = catalog;
    S.inventory   = inventory;
    S.opt.presets = presets;

    initTabs();
    initBuildTab();
    initInventoryTab();
    initOptimizerTab();

    document.getElementById('catalog-info').textContent =
      `${catalog.artifacts.length} арт · ${catalog.containers.length} конт · ${catalog.armors.length} костюмов`;

    document.getElementById('loading-overlay').style.display = 'none';
    document.getElementById('app').style.display = 'block';
  } catch (e) {
    console.error(e);
    const msg = e.status === 401
      ? 'Сессия истекла. <a href="/login">Войдите снова</a>.'
      : 'Не удалось подключиться к серверу: ' + e.message;
    document.getElementById('error-text').innerHTML = msg;
    document.getElementById('loading-overlay').style.display = 'none';
    document.getElementById('error-overlay').style.display = 'flex';
  }
});

function setLoadingText(t) {
  document.getElementById('loading-text').textContent = t;
}

/* ═══════════════════ TABS ═══════════════════ */
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(s => {
        s.classList.remove('active'); s.hidden = true;
      });
      btn.classList.add('active');
      const sec = document.getElementById('tab-' + btn.dataset.tab);
      sec.classList.add('active'); sec.hidden = false;
    });
  });
}

/* ═══════════════════ HELPERS ═══════════════════ */
function fmtVal(val, unit, direction) {
  if (val === undefined || val === null) return '—';
  const n = parseFloat(val);
  const sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(unit === '%' ? 1 : (unit === 'кг' ? 2 : 0)) + (unit || '');
}

function statColor(direction, value) {
  const v = parseFloat(value);
  if (direction === 1) return v > 0 ? 'positive' : (v < 0 ? 'negative' : 'neutral');
  return v > 0 ? 'negative' : (v < 0 ? 'positive' : 'neutral');
}

function colorClass(color) {
  return 'color-' + (color || 'DEFAULT');
}

function artShortStats(art, mode) {
  const sd = S.catalog.stat_defs;
  const props = mode === 'max' ? maxProps(art) : avgProps(art);
  return Object.entries(props)
    .filter(([k]) => sd[k])
    .slice(0, 3)
    .map(([k, v]) => {
      const d = sd[k]; const cls = d.direction === 1 && v >= 0 ? 'p' : 'n';
      return `<span class="${cls}">${fmtVal(v, d.unit, d.direction)} ${d.name_ru}</span>`;
    }).join('<br>');
}

function avgProps(art) {
  const out = {};
  for (const [k, r] of Object.entries(art.props)) out[k] = (r.min + r.max) / 2;
  return out;
}
function maxProps(art) {
  const out = {};
  for (const [k, r] of Object.entries(art.props)) out[k] = r.max;
  return out;
}

function getMode() {
  return document.querySelector('input[name="calc-mode"]:checked')?.value || 'avg';
}

/* ═══════════════════ BUILD TAB ═══════════════════ */
function initBuildTab() {
  // Populate armor select
  const armorSel = document.getElementById('armor-select');
  S.catalog.armors.forEach(a => {
    const o = new Option(a.name + (a.weight ? ` (${a.weight}кг)` : ''), a.id);
    armorSel.add(o);
  });
  armorSel.addEventListener('change', () => {
    S.build.armorId = armorSel.value || null;
    renderArmorMini();
    triggerCalc();
  });

  // Populate container select
  const contSel = document.getElementById('container-select');
  S.catalog.containers.forEach(c => {
    const o = new Option(`${c.name} [${c.slots} сл. · ${c.efficiency_pct}%]`, c.id);
    contSel.add(o);
  });
  contSel.addEventListener('change', () => {
    const c = S.catalog.containers.find(x => x.id === contSel.value);
    S.build.containerId = contSel.value || null;
    S.build.slots = c ? Array(c.slots).fill(null) : [];
    renderContainerInfo(c);
    renderSlots();
    triggerCalc();
  });

  // Mode radio
  document.querySelectorAll('input[name="calc-mode"]').forEach(r =>
    r.addEventListener('change', () => { S.build.mode = r.value; triggerCalc(); })
  );
  // Max HP input
  document.getElementById('max-hp-input').addEventListener('input', e => {
    S.build.maxHp = parseFloat(e.target.value) || 100;
    triggerCalc();
  });

  // Picker modal
  document.getElementById('modal-backdrop').addEventListener('click', closePicker);
  document.getElementById('modal-close').addEventListener('click', closePicker);
  document.getElementById('picker-search').addEventListener('input', e => {
    S.picker.search = e.target.value.toLowerCase();
    renderPickerList();
  });
}

function renderArmorMini() {
  const el = document.getElementById('armor-stats-mini');
  if (!S.build.armorId) { el.innerHTML = ''; el.classList.add('hidden'); return; }
  const a = S.catalog.armors.find(x => x.id === S.build.armorId);
  if (!a) return;
  const sd = S.catalog.stat_defs;
  const chips = Object.entries(a.stats)
    .filter(([, v]) => v !== 0)
    .map(([k, v]) => {
      const d = sd[k];
      return `<span class="mini-stat-chip">${d ? d.name_ru : k}: ${fmtVal(v, d?.unit, d?.direction)}</span>`;
    }).join('');
  el.innerHTML = chips;
  el.classList.remove('hidden');
}

function renderContainerInfo(c) {
  const el = document.getElementById('container-info');
  if (!c) { el.classList.add('hidden'); return; }
  document.getElementById('cont-slots').innerHTML = `Слотов: <strong>${c.slots}</strong>`;
  document.getElementById('cont-eff').innerHTML   = `Эффективность: <strong>${c.efficiency_pct}%</strong>`;
  document.getElementById('cont-prot').innerHTML  = `Защита: <strong>${c.inner_protection}%</strong>`;
  el.classList.remove('hidden');
}

function renderSlots() {
  const cont = S.catalog.containers.find(c => c.id === S.build.containerId);
  const slots = cont ? cont.slots : 0;
  const badge = document.getElementById('slots-badge');
  badge.textContent = `${S.build.slots.filter(Boolean).length}/${slots}`;

  const container = document.getElementById('artifact-slots');
  container.innerHTML = '';
  for (let i = 0; i < slots; i++) {
    const artId = S.build.slots[i];
    const art = artId ? S.catalog.artifacts.find(a => a.id === artId) : null;
    const div = document.createElement('div');
    div.className = 'slot ' + (art ? 'filled ' + colorClass(art.color) : '');
    div.dataset.slot = i;
    if (art) {
      div.innerHTML = `
        <button class="slot-remove" data-slot="${i}" title="Убрать">✕</button>
        <div class="slot-art-name">${art.name}</div>
        <div class="slot-art-stats">${artShortStats(art, getMode())}</div>`;
      div.querySelector('.slot-remove').addEventListener('click', e => {
        e.stopPropagation();
        S.build.slots[parseInt(e.currentTarget.dataset.slot)] = null;
        renderSlots();
        triggerCalc();
      });
    } else {
      div.innerHTML = `<div class="slot-empty-icon">+</div><div class="slot-empty-text">Добавить<br>артефакт</div>`;
    }
    div.addEventListener('click', () => openPicker(i));
    container.appendChild(div);
  }

  if (slots === 0) {
    container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:16px 0">Сначала выберите контейнер</div>';
  }
}

async function triggerCalc() {
  const artIds = S.build.slots.filter(Boolean);
  const body = {
    armor_id:     S.build.armorId    || null,
    container_id: S.build.containerId|| null,
    artifact_ids: artIds,
    mode:         S.build.mode,
    max_hp:       S.build.maxHp,
  };
  const result = await api.post('/api/calc', body);
  renderStats(result);
}

function renderStats(result) {
  document.getElementById('eff-hp-value').textContent =
    result.effective_hp != null ? result.effective_hp.toFixed(1) : '—';

  const list = document.getElementById('stats-list');
  const sd = S.catalog.stat_defs;
  const stats = result.stats || {};

  // Group: artifact bonuses, armor protections, accumulations
  const artStats   = [];
  const armStats   = [];
  const accStats   = [];
  const otherStats = [];

  for (const [k, v] of Object.entries(stats)) {
    if (Math.abs(v) < 0.0001) continue;
    const def = sd[k];
    if (!def) { otherStats.push([k, v, null]); continue; }
    const row = [k, v, def];
    if (def.direction === -1) accStats.push(row);
    else if (def.sources.includes('armor')) armStats.push(row);
    else artStats.push(row);
  }

  if (!artStats.length && !armStats.length && !accStats.length) {
    list.innerHTML = '<div class="stats-placeholder">Добавьте артефакты</div>';
    return;
  }

  let html = '';
  if (armStats.length) {
    html += `<div class="stat-section-title">Защиты костюма</div>`;
    for (const [k, v, def] of armStats) {
      const cls = statColor(def.direction, v);
      html += `<div class="stat-row"><span class="stat-name">${def.name_ru}</span>
        <span class="stat-value ${cls}">${fmtVal(v, def.unit, def.direction)}</span></div>`;
    }
  }
  if (artStats.length) {
    html += `<div class="stat-section-title">Бонусы артефактов</div>`;
    for (const [k, v, def] of artStats) {
      const cls = statColor(def.direction, v);
      html += `<div class="stat-row"><span class="stat-name">${def.name_ru}</span>
        <span class="stat-value ${cls}">${fmtVal(v, def.unit, def.direction)}</span></div>`;
    }
  }
  if (accStats.length) {
    html += `<div class="stat-section-title">Накопления (штрафы)</div>`;
    for (const [k, v, def] of accStats) {
      const cls = statColor(def.direction, v);
      html += `<div class="stat-row"><span class="stat-name">${def.name_ru}</span>
        <span class="stat-value ${cls}">${fmtVal(v, def.unit, def.direction)}</span></div>`;
    }
  }
  list.innerHTML = html;
}

/* ═══════════════════ PICKER MODAL ═══════════════════ */
function openPicker(slotIdx) {
  if (!S.build.containerId) return;
  S.picker.slot = slotIdx;
  S.picker.search = '';
  document.getElementById('picker-search').value = '';
  S.picker.filter = 'all';

  // Build category list
  const cats = [...new Set(S.catalog.artifacts.map(a => a.category))].sort();
  const catEl = document.getElementById('picker-cats');
  catEl.innerHTML = `<button class="picker-cat-btn active" data-cat="all">Все</button>` +
    cats.map(c => `<button class="picker-cat-btn" data-cat="${c}">${catLabel(c)}</button>`).join('');
  catEl.querySelectorAll('.picker-cat-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      catEl.querySelectorAll('.picker-cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.picker.filter = btn.dataset.cat;
      renderPickerList();
    });
  });

  renderPickerList();
  document.getElementById('picker-modal').removeAttribute('hidden');
  document.getElementById('picker-search').focus();
}

function closePicker() {
  document.getElementById('picker-modal').setAttribute('hidden', '');
}

function catLabel(cat) {
  const map = {
    'artefact/electrophysical': 'Электрофизические',
    'artefact/gravitational':   'Гравитационные',
    'artefact/chemical':        'Химические',
    'artefact/thermal':         'Термальные',
    'artefact/biological':      'Биологические',
    'artefact/radioactive':     'Радиоактивные',
  };
  return map[cat] || cat.split('/').pop();
}

function renderPickerList() {
  const q = S.picker.search;
  const cat = S.picker.filter;
  const mode = getMode();
  const sd = S.catalog.stat_defs;
  const usedIds = new Set(S.build.slots.filter(Boolean));

  const items = S.catalog.artifacts.filter(a => {
    if (cat !== 'all' && a.category !== cat) return false;
    if (q && !a.name.toLowerCase().includes(q)) return false;
    return true;
  });

  const list = document.getElementById('picker-list');
  list.innerHTML = items.map(a => {
    const props = mode === 'max' ? maxProps(a) : avgProps(a);
    const statsHtml = Object.entries(props)
      .filter(([k]) => sd[k])
      .map(([k, v]) => {
        const d = sd[k];
        const cls = d.direction === 1 && v > 0 ? 'p' : (d.direction === -1 && v > 0 ? 'n' : '');
        return `<span class="${cls}">${fmtVal(v, d.unit, d.direction)} ${d.name_ru}</span>`;
      }).join('<br>');
    const dim = usedIds.has(a.id) ? ' style="opacity:.45"' : '';
    return `<div class="picker-item ${colorClass(a.color)}" data-id="${a.id}"${dim}>
      <div class="picker-item-name">${a.name}</div>
      <div class="picker-item-stats">${statsHtml}</div>
    </div>`;
  }).join('') || '<div style="color:var(--text-dim);padding:20px;text-align:center">Ничего не найдено</div>';

  list.querySelectorAll('.picker-item').forEach(el => {
    el.addEventListener('click', () => {
      S.build.slots[S.picker.slot] = el.dataset.id;
      closePicker();
      renderSlots();
      triggerCalc();
    });
  });
}

/* ═══════════════════ INVENTORY TAB ═══════════════════ */
function initInventoryTab() {
  document.getElementById('inv-search').addEventListener('input', e => renderInvList(e.target.value));
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderInvList(document.getElementById('inv-search').value);
    });
  });
  document.getElementById('save-inv-btn').addEventListener('click', saveInventory);
  renderInvList('');
}

function renderInvList(q) {
  const filter = document.querySelector('.filter-btn.active')?.dataset.filter || 'all';
  const ql = q.toLowerCase();
  const sd = S.catalog.stat_defs;
  const list = document.getElementById('inv-list');

  const sections = [];
  if (filter === 'all' || filter === 'artifact') {
    S.catalog.artifacts.filter(a => !ql || a.name.toLowerCase().includes(ql))
      .forEach(a => sections.push({ type: 'artifact', item: a }));
  }
  if (filter === 'all' || filter === 'container') {
    S.catalog.containers.filter(c => !ql || c.name.toLowerCase().includes(ql))
      .forEach(c => sections.push({ type: 'container', item: c }));
  }
  if (filter === 'all' || filter === 'armor') {
    S.catalog.armors.filter(a => !ql || a.name.toLowerCase().includes(ql))
      .forEach(a => sections.push({ type: 'armor', item: a }));
  }

  list.innerHTML = sections.map(({ type, item }) => {
    const sel = isInInventory(type, item.id);
    let statsHtml = '';
    if (type === 'artifact') {
      const mode = getMode();
      const props = mode === 'max' ? maxProps(item) : avgProps(item);
      statsHtml = Object.entries(props).filter(([k]) => sd[k]).slice(0, 4)
        .map(([k, v]) => {
          const d = sd[k];
          return `<span style="color:${d.direction===1&&v>0?'var(--green)':d.direction===-1&&v>0?'var(--red)':'var(--text-dim)'}">${fmtVal(v,d.unit,d.direction)} ${d.name_ru}</span>`;
        }).join('<br>');
    } else if (type === 'container') {
      statsHtml = `Слоты: ${item.slots} · Эффект.: ${item.efficiency_pct}% · Защита: ${item.inner_protection}%`;
    } else {
      statsHtml = Object.entries(item.stats||{}).filter(([,v])=>v!==0).slice(0,4)
        .map(([k,v]) => `${sd[k]?.name_ru||k}: ${v}`).join(' · ');
    }
    const catLabel2 = type === 'artifact' ? catLabel(item.category)
      : type === 'container' ? 'Контейнер' : item.category.split('/').pop();

    return `<div class="inv-card ${colorClass(item.color||'DEFAULT')} ${sel?'selected':''}" data-type="${type}" data-id="${item.id}">
      <div class="inv-card-check">${sel ? '✓' : ''}</div>
      <div class="inv-card-body">
        <div class="inv-card-name">${item.name}</div>
        <div class="inv-card-cat">${catLabel2}${item.weight ? ' · ' + item.weight + ' кг' : ''}</div>
        <div class="inv-card-stats">${statsHtml}</div>
      </div>
    </div>`;
  }).join('') || '<div style="color:var(--text-dim);padding:20px;text-align:center;grid-column:1/-1">Ничего не найдено</div>';

  list.querySelectorAll('.inv-card').forEach(card => {
    card.addEventListener('click', () => {
      toggleInventory(card.dataset.type, card.dataset.id);
      renderInvList(q);
    });
  });
}

function isInInventory(type, id) {
  const key = type === 'artifact' ? 'artifact_ids' : type === 'container' ? 'container_ids' : 'armor_ids';
  return S.inventory[key].includes(id);
}

function toggleInventory(type, id) {
  const key = type === 'artifact' ? 'artifact_ids' : type === 'container' ? 'container_ids' : 'armor_ids';
  const arr = S.inventory[key];
  const idx = arr.indexOf(id);
  if (idx === -1) arr.push(id); else arr.splice(idx, 1);
}

async function saveInventory() {
  await api.post('/api/inventory', S.inventory);
  const el = document.getElementById('inv-save-status');
  el.textContent = '✓ Сохранено';
  setTimeout(() => el.textContent = '', 2000);
}

/* ═══════════════════ OPTIMIZER TAB ═══════════════════ */
function initOptimizerTab() {
  // Preset buttons
  const presetEl = document.getElementById('preset-btns');
  presetEl.innerHTML = S.opt.presets.map(p =>
    `<button class="preset-btn" data-pid="${p.id}" title="${p.description}">${p.name}</button>`
  ).join('') + '<div class="preset-desc" id="preset-desc"></div>';

  presetEl.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      presetEl.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.opt.activePreset = btn.dataset.pid;
      const p = S.opt.presets.find(x => x.id === btn.dataset.pid);
      document.getElementById('preset-desc').textContent = p?.description || '';
      S.opt.weights = Object.assign({}, p?.weights || {});
      renderSliders();
    });
  });

  // Sliders for all artifact stats
  renderSliders();

  document.getElementById('optimize-btn').addEventListener('click', runOptimize);
}

function renderSliders() {
  const sd = S.catalog.stat_defs;
  const artKeys = Object.values(sd)
    .filter(d => d.sources.includes('artifact'))
    .sort((a, b) => a.name_ru.localeCompare(b.name_ru));

  const cont = document.getElementById('sliders-container');
  cont.innerHTML = artKeys.map(d => {
    const val = S.opt.weights[d.key] ?? 0;
    return `<div class="slider-row">
      <span class="slider-name" title="${d.name_ru}">${d.name_ru}</span>
      <input type="range" class="slider-range" data-key="${d.key}"
        min="-5" max="5" step="0.5" value="${val}">
      <span class="slider-value ${val>0?'pos':val<0?'neg':'zero'}" id="sv-${d.key}">${val>0?'+':''}${val}</span>
    </div>`;
  }).join('');

  cont.querySelectorAll('.slider-range').forEach(s => {
    s.addEventListener('input', () => {
      const k = s.dataset.key; const v = parseFloat(s.value);
      S.opt.weights[k] = v;
      const el = document.getElementById('sv-' + k);
      el.textContent = (v > 0 ? '+' : '') + v;
      el.className = 'slider-value ' + (v > 0 ? 'pos' : v < 0 ? 'neg' : 'zero');
    });
  });
}

async function runOptimize() {
  const hasItems = S.inventory.artifact_ids.length ||
                   S.inventory.container_ids.length ||
                   S.inventory.armor_ids.length;
  if (!hasItems) {
    document.getElementById('opt-results').innerHTML =
      `<div class="no-inv-warning">Сначала выберите свои предметы во вкладке «Инвентарь»</div>`;
    return;
  }

  const btn = document.getElementById('optimize-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Подбираю...';

  const mode   = document.querySelector('input[name="opt-mode"]:checked')?.value || 'avg';
  const maxHp  = parseFloat(document.getElementById('opt-max-hp').value) || 100;

  const results = await api.post('/api/optimize', {
    inventory: S.inventory,
    weights:   S.opt.weights,
    mode, max_hp: maxHp, top_n: 5,
  });

  btn.disabled = false;
  btn.textContent = '🎯 Подобрать оптимальную сборку';
  renderOptResults(results);
}

function renderOptResults(results) {
  const el = document.getElementById('opt-results');
  const sd = S.catalog.stat_defs;
  if (!results.length) {
    el.innerHTML = `<div class="no-inv-warning">Нет подходящих сборок. Проверьте инвентарь.</div>`;
    return;
  }

  el.innerHTML = results.map((r, i) => {
    const rankClass = i === 0 ? 'rank-1' : '';
    const rankLabel = i === 0 ? '🥇 Лучшая сборка' : `#${i + 1}`;
    const rankLabelCls = i === 0 ? 'opt-rank opt-rank-1' : 'opt-rank';

    const armorTag = r.armor
      ? `<span class="opt-tag armor-tag">🛡 ${r.armor.name}</span>` : '';
    const contTag  = `<span class="opt-tag cont-tag">📦 ${r.container.name} [${r.container.slots} сл.]</span>`;
    const artTags  = r.artifacts.map(a => `<span class="opt-tag art-tag">☢ ${a.name}</span>`).join('');

    const stats = r.totals?.stats || {};
    const chips = Object.entries(stats)
      .filter(([, v]) => Math.abs(v) > 0.001 && sd[_k = Object.keys(sd).find(k=>k===Object.keys(stats).find(sk=>sk===Object.keys(stats).find(x=>x===_k)))||_k||' '])
      .slice(0, 10);

    // Build stat chips more reliably
    const statChips = Object.entries(stats)
      .filter(([k, v]) => sd[k] && Math.abs(v) > 0.001)
      .sort(([,a],[,b]) => Math.abs(b) - Math.abs(a))
      .slice(0, 10)
      .map(([k, v]) => {
        const d = sd[k];
        const cls = d.direction === 1 ? (v > 0 ? 'pos' : 'neg') : (v > 0 ? 'neg' : 'pos');
        return `<div class="opt-stat-chip">${d.name_ru}: <span class="v ${cls}">${fmtVal(v, d.unit, d.direction)}</span></div>`;
      }).join('');

    return `<div class="opt-result-card ${rankClass}">
      <div class="opt-result-header">
        <span class="${rankLabelCls}">${rankLabel}</span>
        <span class="opt-eff-hp">${r.totals?.effective_hp?.toFixed(1) || '—'} <small>Приведёнка</small></span>
        <button class="btn-apply" data-idx="${i}">Применить →</button>
      </div>
      <div class="opt-items">${armorTag}${contTag}${artTags}</div>
      <div class="opt-stats">${statChips}</div>
    </div>`;
  }).join('');

  el.querySelectorAll('.btn-apply').forEach(btn => {
    btn.addEventListener('click', () => applyBuild(results[parseInt(btn.dataset.idx)]));
  });
}

function applyBuild(result) {
  // Switch to Build tab
  document.querySelector('.tab[data-tab="build"]').click();

  // Set armor
  const armorSel = document.getElementById('armor-select');
  armorSel.value = result.armor?.id || '';
  S.build.armorId = result.armor?.id || null;
  renderArmorMini();

  // Set container
  const contSel = document.getElementById('container-select');
  contSel.value = result.container.id;
  S.build.containerId = result.container.id;
  const cont = S.catalog.containers.find(c => c.id === result.container.id);
  renderContainerInfo(cont);

  // Set artifacts
  S.build.slots = result.artifacts.map(a => a.id);
  // Pad to container slots
  const slots = cont?.slots || 0;
  while (S.build.slots.length < slots) S.build.slots.push(null);

  renderSlots();
  triggerCalc();
}
