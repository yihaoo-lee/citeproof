const $ = (id) => document.getElementById(id);
const FIELDS = ["problem", "method", "dataset", "conclusion", "limitation", "reproducibility"];
const FIELD_LABEL = { problem: "问题", method: "方法", dataset: "数据集", conclusion: "结论", limitation: "局限", reproducibility: "可复现性" };
const LEVEL_LABEL = { exact: "精确匹配", normalized: "归一化匹配", anchored: "锚点定位" };
const STANCE_LABEL = { consensus: "共识", partial: "部分共识", conflict: "分歧", insufficient: "证据不足" };
const PAGE_SIZE = 10;
const EXAMPLES = [
  "大语言模型幻觉检测",
  "检索增强生成中的知识更新",
  "医学问答的事实一致性",
];

let papers = [];
let selected = new Set();
let page = 1;
let matrix = null;
let currentJobId = null;
let searched = false;
let debounceTimer = null;

async function api(path, body) {
  const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = "请求失败 " + r.status;
    try {
      const e = await r.json();
      if (e.detail) msg = typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail);
    } catch (_) { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

function setStatus(msg, isError, retry) {
  const status = $("status");
  status.textContent = msg;
  status.classList.toggle("error", !!isError);
  if (retry) {
    const button = document.createElement("button");
    button.className = "ghost retry-btn";
    button.textContent = "重试";
    button.onclick = analyze;
    status.appendChild(button);
  }
}

function setDegradeStatus(msg) {
  const status = $("status");
  status.classList.remove("error");
  status.classList.add("degrade");
  status.textContent = msg;
}

async function health() {
  try {
    const h = await api("/api/health");
    $("health").textContent = h.demo_mode ? "演示模式（离线）" : (h.llm_configured ? "已就绪" : "未配置 key");
    $("health").classList.add("ok");
  } catch (e) {
    $("health").textContent = "服务异常";
  }
}

function applyTheme() {
  if (localStorage.getItem("theme") === "dark") {
    document.body.classList.remove("light");
    $("theme-btn").textContent = "浅色";
  } else {
    document.body.classList.add("light");
    $("theme-btn").textContent = "深色";
  }
}

function toggleTheme() {
  const light = document.body.classList.toggle("light");
  localStorage.setItem("theme", light ? "light" : "dark");
  $("theme-btn").textContent = light ? "深色" : "浅色";
}

function resolveLimit() {
  if ($("limit").value === "custom") {
    const n = parseInt($("custom-limit").value, 10) || 10;
    return Math.max(1, Math.min(20, n));
  }
  return parseInt($("limit").value, 10);
}

async function search() {
  const q = $("query").value.trim();
  if (!q) { setStatus("请输入研究问题", true); return; }
  setStatus("检索中…");
  try {
    const data = await api("/api/search", {
      query: q,
      limit: resolveLimit(),
      sort: $("sort").value,
    });
    papers = data.papers || [];
    searched = true;
    selected = new Set(papers.filter((p, i) => p.has_fulltext && i < 5).map((p) => p.id));
    page = 1;
    renderResults();
    const fb = data.fallback ? "（OpenAlex 不稳定，已切换 arXiv 兜底）" : "";
    setStatus(papers.length ? `检索到 ${papers.length} 篇${fb}，勾选要分析的论文` : "没有检索到论文，请换一个关键词重试", !papers.length);
  } catch (e) {
    setStatus(e.message, true);
  }
}

function filteredPapers() {
  return $("fulltext-only").checked ? papers.filter((p) => p.has_fulltext) : papers;
}

function renderResults() {
  const list = filteredPapers();
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  if (page > pages) page = pages;
  const slice = list.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const box = $("results");
  box.innerHTML = "";
  slice.forEach((p) => {
    const row = document.createElement("div");
    row.className = "result";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selected.has(p.id);
    cb.onchange = () => { cb.checked ? selected.add(p.id) : selected.delete(p.id); updateHint(); };

    const body = document.createElement("div");
    body.className = "body";
    const title = document.createElement("div");
    title.className = "t";
    title.textContent = p.title;
    const meta = document.createElement("div");
    meta.className = "m";
    const authors = (p.authors || []).slice(0, 3).join(", ") || "本地上传";
    const metaText = document.createElement("span");
    metaText.textContent = `${p.year || "—"} · ${authors} · ${p.venue || p.source} · 被引 ${p.cited_by_count ?? "—"}`;
    meta.appendChild(metaText);
    const pdfBadge = document.createElement("span");
    pdfBadge.className = "badge " + (p.has_fulltext ? "pdf" : "abstract");
    pdfBadge.textContent = p.has_fulltext ? "有全文" : "仅摘要";
    meta.appendChild(pdfBadge);
    body.appendChild(title);
    body.appendChild(meta);
    if (p.url) {
      const foot = document.createElement("div");
      foot.className = "rfoot";
      const link = document.createElement("a");
      link.className = "orig";
      link.href = p.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "查看原文 →";
      foot.appendChild(link);
      body.appendChild(foot);
    }
    row.appendChild(cb);
    row.appendChild(body);
    box.appendChild(row);
  });
  box.classList.remove("hidden");
  $("toolbar").classList.remove("hidden");
  renderPager(pages, list.length);
  updateHint();
}

function renderPager(pages, total) {
  const pager = $("pager");
  if (pages <= 1) { pager.classList.add("hidden"); return; }
  pager.classList.remove("hidden");
  pager.innerHTML = "";
  const prev = document.createElement("button");
  prev.className = "ghost";
  prev.textContent = "上一页";
  prev.disabled = page <= 1;
  prev.onclick = () => { page--; renderResults(); };
  const next = document.createElement("button");
  next.className = "ghost";
  next.textContent = "下一页";
  next.disabled = page >= pages;
  next.onclick = () => { page++; renderResults(); };
  const info = document.createElement("span");
  info.textContent = `第 ${page}/${pages} 页 · 共 ${total} 篇`;
  pager.appendChild(prev);
  pager.appendChild(info);
  pager.appendChild(next);
}

function updateHint() {
  $("selection-hint").textContent = `${selected.size} 篇已选`;
}

async function analyze() {
  const chosen = papers.filter((p) => selected.has(p.id));
  if (!chosen.length) { setStatus("请先勾选至少一篇论文", true); return; }
  $("analyze-btn").disabled = true;
  try {
    const resp = await api("/api/analyze", { query: $("query").value.trim() || "（未命名检索）", papers: chosen.map((p) => ({ id: p.id })) });
    if (resp.error) throw new Error(resp.error);
    if (!resp.job_id) throw new Error("任务创建失败");
    await pollJob(resp.job_id);
    currentJobId = resp.job_id;
    renderMatrix();
    const failures = matrix.rows.filter((row) => ["scanned_or_empty", "download_failed", "failed"].some((s) => (row.parse_status || "").startsWith(s))).length;
    if (failures) {
      setDegradeStatus(`完成；${failures} 篇 PDF 下载或解析失败，结果可能仅基于摘要`);
    } else {
      setStatus("完成");
    }
  } catch (e) {
    setStatus(e.message, true, !!e.retryable);
  } finally {
    $("analyze-btn").disabled = false;
  }
}

async function pollJob(id) {
  while (true) {
    const j = await api("/api/job/" + id);
    if (j.status === "done") { matrix = j.result; return; }
    if (j.status === "error") {
      const error = new Error(j.error || "分析失败，请重试");
      error.retryable = true;
      throw error;
    }
    const label = j.stage === "prepare" ? "正在下载/解析" : "正在校验";
    setStatus(`${label}第 ${j.done}/${j.total} 篇…`);
    await new Promise((r) => setTimeout(r, 800));
  }
}

function renderMatrix() {
  const s = matrix.stats;
  $("s-papers").textContent = s.papers;
  $("s-hit").textContent = (s.quote_hit_rate * 100).toFixed(0) + "%";
  $("s-discard").textContent = (s.discard_rate * 100).toFixed(0) + "%";
  $("s-support").textContent = (s.support_rate * 100).toFixed(0) + "%";
  $("s-complete").textContent = (s.field_completeness * 100).toFixed(0) + "%";
  renderFunnel();
  $("stats-card").classList.remove("hidden");
  document.querySelectorAll(".export-row button").forEach((b) => { b.disabled = false; });

  const table = $("matrix");
  table.innerHTML = "";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(th("论文"));
  FIELDS.forEach((f) => hr.appendChild(th(FIELD_LABEL[f])));
  thead.appendChild(hr);
  table.appendChild(thead);

  const rows = matrix.rows.slice().sort((a, b) => (b.claims || []).length - (a.claims || []).length);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const tdPaper = document.createElement("td");
    tdPaper.className = "paper";
    tdPaper.textContent = `${row.title}${row.year ? " (" + row.year + ")" : ""}`;
    const notes = [];
    if (row.stub) notes.push(row.stub_reason || "启发式抽取");
    if (row.partial) notes.push("节选分析（首/中/尾）");
    if (row.parse_status && ["uploaded", "downloaded"].indexOf(row.parse_status) === -1) notes.push(statusLabel(row.parse_status));
    if (!(row.claims || []).length) notes.push("未找到可验证引用");
    if (notes.length) {
      const noteEl = document.createElement("div");
      noteEl.className = "src";
      noteEl.textContent = notes.join(" · ");
      tdPaper.appendChild(noteEl);
    }
    tr.appendChild(tdPaper);

    FIELDS.forEach((f) => {
      const td = document.createElement("td");
      td.className = "field";
      const val = row.fields[f] || "";
      const claims = (row.claims || []).filter((c) => c.field === f);
      if (val && !claims.length) {
        td.classList.add("unverified");
        td.textContent = "未找到原文出处";
        td.title = "程序未能在 PDF 原文中定位到对应引用，该概括不作为已核验结论";
      } else if (val) {
        const preview = document.createElement("div");
        preview.className = "cell-preview";
        preview.textContent = val;
        td.appendChild(preview);
        td.onclick = () => openDrawer(row, f);
      } else {
        td.className = "field empty";
        td.textContent = "—";
      }
      if (claims.length) {
        const entailment = claims[0].entailment || "unjudged";
        td.classList.add("evidence-" + entailment);
        td.title = { supported: "原文支持该概括", partial: "原文仅部分支持该概括", unsupported: "原文不支持该概括", unjudged: "语义支持尚未判定" }[entailment] || "语义支持尚未判定";
        const dot = document.createElement("span");
        dot.className = "dot " + entailment;
        td.appendChild(dot);
        if (claims.length > 1) {
          const cnt = document.createElement("span");
          cnt.className = "count";
          cnt.textContent = claims.length;
          td.appendChild(cnt);
        }
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  renderSynthesis();
  $("matrix-card").classList.remove("hidden");
}

function funnelRow(label, value, denom, barClass, sub, valueClass) {
  const wrap = document.createElement("div");
  const row = document.createElement("div");
  row.className = "funnel-row";
  const lab = document.createElement("div");
  lab.className = "funnel-label";
  lab.textContent = label;
  const track = document.createElement("div");
  track.className = "funnel-track";
  const bar = document.createElement("div");
  bar.className = "funnel-bar " + (barClass || "");
  bar.style.width = denom > 0 ? Math.max(0, Math.min(100, (value / denom) * 100)) + "%" : "0%";
  track.appendChild(bar);
  const val = document.createElement("div");
  val.className = "funnel-val " + (valueClass || "");
  val.textContent = value;
  row.appendChild(lab);
  row.appendChild(track);
  row.appendChild(val);
  wrap.appendChild(row);
  if (sub) {
    const s = document.createElement("div");
    s.className = "funnel-sub";
    s.textContent = sub;
    wrap.appendChild(s);
  }
  return wrap;
}

function funnelStackRow(label, parts, total, stackTotal, value, sub) {
  const wrap = document.createElement("div");
  const row = document.createElement("div");
  row.className = "funnel-row";
  const lab = document.createElement("div");
  lab.className = "funnel-label";
  lab.textContent = label;
  const track = document.createElement("div");
  track.className = "funnel-track";
  const stack = document.createElement("div");
  stack.className = "funnel-stack";
  stack.style.width = total > 0 ? Math.max(0, Math.min(100, (stackTotal / total) * 100)) + "%" : "0%";
  parts.forEach(([n, cls]) => {
    if (!n || !stackTotal) return;
    const seg = document.createElement("span");
    seg.className = cls;
    seg.style.width = (n / stackTotal) * 100 + "%";
    stack.appendChild(seg);
  });
  track.appendChild(stack);
  const val = document.createElement("div");
  val.className = "funnel-val";
  val.textContent = value;
  row.appendChild(lab);
  row.appendChild(track);
  row.appendChild(val);
  wrap.appendChild(row);
  if (sub) {
    const s = document.createElement("div");
    s.className = "funnel-sub";
    s.textContent = sub;
    wrap.appendChild(s);
  }
  return wrap;
}

function renderFunnel() {
  const box = $("funnel");
  box.innerHTML = "";
  const rows = (matrix && matrix.rows) || [];
  const s = (matrix && matrix.stats) || {};
  const total = rows.length;

  const seg1 = document.createElement("div");
  seg1.className = "funnel-seg";
  const t1 = document.createElement("div");
  t1.className = "funnel-title";
  t1.textContent = "论文筛选（篇）";
  seg1.appendChild(t1);
  const isFulltext = (r) => r.parse_status === "uploaded" || r.parse_status === "downloaded";
  const hasClaims = (r) => (r.claims || []).length > 0;
  const fulltext = rows.filter(isFulltext).length;
  const degraded = total - fulltext;
  const fulltextWithClaims = rows.filter((r) => isFulltext(r) && hasClaims(r)).length;
  const degradedWithClaims = rows.filter((r) => !isFulltext(r) && hasClaims(r)).length;
  const withClaims = fulltextWithClaims + degradedWithClaims;
  seg1.appendChild(funnelRow("纳入分析", total, total));
  seg1.appendChild(funnelRow("全文可解析", fulltext, total, "", degraded > 0 ? `其余 ${degraded} 篇降级摘要级` : ""));
  seg1.appendChild(funnelStackRow(
    "找到可验证引用",
    [[fulltextWithClaims, "c-accent"], [degradedWithClaims, "c-muted"]],
    total,
    withClaims,
    withClaims,
    withClaims > 0 ? `其中全文 ${fulltextWithClaims} 篇、摘要级 ${degradedWithClaims} 篇` : "暂无可验证引用"
  ));
  box.appendChild(seg1);

  const seg2 = document.createElement("div");
  seg2.className = "funnel-seg";
  const t2 = document.createElement("div");
  t2.className = "funnel-title";
  t2.textContent = "证据校验（条）";
  seg2.appendChild(t2);
  const attempts = s.attempts || 0;
  const kept = s.kept || 0;
  const discard = Math.max(0, attempts - kept);
  const denom = Math.max(attempts, 1);

  let exact = 0, normalized = 0, anchored = 0;
  let supported = 0, partial = 0, unsupported = 0, unjudged = 0;
  rows.forEach((r) => (r.claims || []).forEach((c) => {
    if (c.match_level === "exact") exact++;
    else if (c.match_level === "normalized") normalized++;
    else if (c.match_level === "anchored") anchored++;
    if (c.entailment === "supported") supported++;
    else if (c.entailment === "partial") partial++;
    else if (c.entailment === "unsupported") unsupported++;
    else unjudged++;
  }));

  seg2.appendChild(funnelRow("模型提出证据候选", attempts, denom));
  seg2.appendChild(funnelRow("逐字校验通过", kept, denom, "", `exact ${exact} / normalized ${normalized} / anchored ${anchored}`));
  seg2.appendChild(funnelRow("丢弃", discard, denom, "orange", "核不上原文，已丢弃", "orange"));

  const wrap = document.createElement("div");
  const row = document.createElement("div");
  row.className = "funnel-row";
  const lab = document.createElement("div");
  lab.className = "funnel-label";
  lab.textContent = "语义复审";
  const track = document.createElement("div");
  track.className = "funnel-track";
  const stack = document.createElement("div");
  stack.className = "funnel-stack";
  stack.style.width = denom > 0 ? Math.max(0, Math.min(100, (kept / denom) * 100)) + "%" : "0%";
  [[supported, "c-good"], [partial, "c-warn"], [unsupported, "c-bad"], [unjudged, "c-muted"]].forEach(([n, cls]) => {
    if (!n || !kept) return;
    const seg = document.createElement("span");
    seg.className = cls;
    seg.style.width = (n / kept) * 100 + "%";
    stack.appendChild(seg);
  });
  track.appendChild(stack);
  const val = document.createElement("div");
  val.className = "funnel-val";
  val.textContent = kept;
  row.appendChild(lab);
  row.appendChild(track);
  row.appendChild(val);
  wrap.appendChild(row);
  if (kept > 0) {
    const legend = document.createElement("div");
    legend.className = "funnel-legend";
    [["支持", supported, "c-good"], ["部分支持", partial, "c-warn"], ["不支持", unsupported, "c-bad"], ["未判定", unjudged, "c-muted"]].forEach(([name, n, cls]) => {
      if (!n) return;
      const item = document.createElement("span");
      const dot = document.createElement("i");
      dot.className = cls;
      item.appendChild(dot);
      item.appendChild(document.createTextNode(`${name} ${n}`));
      legend.appendChild(item);
    });
    wrap.appendChild(legend);
  } else {
    const empty = document.createElement("div");
    empty.className = "funnel-sub";
    empty.textContent = "无可复审证据";
    wrap.appendChild(empty);
  }
  seg2.appendChild(wrap);
  box.appendChild(seg2);
}

function synthBadgeClass(stance) {
  return { consensus: "good", partial: "warn", conflict: "bad", insufficient: "muted" }[stance] || "muted";
}

function renderSynthesis() {
  const box = $("synthesis");
  box.innerHTML = "";
  const syn = matrix && matrix.synthesis;
  if (syn === null || syn === undefined) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");

  const title = document.createElement("div");
  title.className = "synth-title";
  title.textContent = "跨论文综合";
  box.appendChild(title);

  const usable = (syn || []).filter((x) => x && x.stance && x.stance !== "insufficient");
  if (!usable.length) {
    const empty = document.createElement("div");
    empty.className = "synth-empty";
    empty.textContent = "同一字段有 2 篇以上论文证据后，将自动综合共识与分歧";
    box.appendChild(empty);
    return;
  }

  syn.forEach((item) => {
    if (!item || !item.field) return;
    const row = document.createElement("div");
    row.className = "synth-row";
    const head = document.createElement("div");
    head.className = "synth-head";
    const field = document.createElement("span");
    field.className = "synth-field";
    field.textContent = FIELD_LABEL[item.field] || item.field;
    const badge = document.createElement("span");
    badge.className = "synth-badge " + synthBadgeClass(item.stance);
    badge.textContent = STANCE_LABEL[item.stance] || item.stance;
    const summary = document.createElement("span");
    summary.className = "synth-summary";
    summary.textContent = item.summary || "";
    head.appendChild(field);
    head.appendChild(badge);
    head.appendChild(summary);
    row.appendChild(head);

    const groups = item.groups || [];
    if (item.stance !== "insufficient" && groups.length) {
      const toggle = document.createElement("span");
      toggle.className = "synth-toggle";
      toggle.textContent = "展开";
      const body = document.createElement("div");
      body.className = "synth-body hidden";
      groups.forEach((g) => {
        const group = document.createElement("div");
        group.className = "synth-group";
        const pos = document.createElement("div");
        pos.className = "synth-pos";
        pos.textContent = "立场：" + (g.position || "—");
        group.appendChild(pos);
        (g.papers || []).forEach((p) => {
          const paper = document.createElement("div");
          paper.className = "synth-paper";
          const pt = document.createElement("div");
          pt.className = "synth-ptitle";
          pt.textContent = `${p.title}${p.year ? " (" + p.year + ")" : ""}`;
          if (p.entailment) {
            const pill = document.createElement("span");
            pill.className = "pill " + p.entailment;
            pill.textContent = p.entailment === "partial" ? "部分支持" : "支持";
            pt.appendChild(pill);
          }
          const q = document.createElement("div");
          q.className = "synth-quote";
          q.textContent = "“" + p.quote + "”";
          const src = document.createElement("span");
          src.className = "src";
          src.textContent = ` 第 ${p.page} 页`;
          q.appendChild(src);
          paper.appendChild(pt);
          paper.appendChild(q);
          group.appendChild(paper);
        });
        body.appendChild(group);
      });
      toggle.onclick = () => {
        const hidden = body.classList.toggle("hidden");
        toggle.textContent = hidden ? "展开" : "收起";
      };
      head.appendChild(toggle);
      row.appendChild(body);
    }
    box.appendChild(row);
  });
}

function th(text) {
  const el = document.createElement("th");
  el.textContent = text;
  return el;
}

function statusLabel(s) {
  if (s && s.startsWith("failed")) return "解析失败";
  return {
    download_failed: "全文下载失败，降级摘要",
    scanned_or_empty: "扫描版/无文字层",
    abstract_only: "仅摘要级证据",
    failed: "解析失败",
  }[s] || s;
}

function auditLevel(level) {
  return {
    exact: "逐字完全一致",
    normalized: "标准化后一致（忽略大小写/连字符/空白）",
    anchored: "锚点定位扩句",
  }[level] || "—";
}

function auditEvidence(level) {
  return { fulltext: "全文级", abstract: "摘要级" }[level] || "—";
}

function auditEntail(entailment, reason) {
  const label = { supported: "支持", partial: "部分支持", unsupported: "不支持" }[entailment] || "未判定";
  return `${label}：${reason || "—"}`;
}

function buildAudit(c) {
  const wrap = document.createElement("div");
  wrap.className = "audit";
  const title = document.createElement("div");
  title.className = "audit-title";
  title.textContent = "审计轨迹";
  wrap.appendChild(title);
  const steps = [
    ["模型提案", c.proposal || "—", true],
    ["锚点定位", c.anchor || "—", true],
    ["服务端扩句", c.quote || "—", false],
    ["逐字比对", auditLevel(c.match_level), false],
    ["证据级别", auditEvidence(c.evidence_level), false],
    ["语义复审", auditEntail(c.entailment, c.reason), false],
  ];
  steps.forEach(([name, val, mono], i) => {
    const step = document.createElement("div");
    step.className = "audit-step";
    const no = document.createElement("div");
    no.className = "audit-no";
    no.textContent = i + 1;
    const body = document.createElement("div");
    body.className = "audit-body";
    const nm = document.createElement("div");
    nm.className = "audit-name";
    nm.textContent = name;
    const v = document.createElement("div");
    v.className = "audit-val" + (mono ? " mono" : "");
    v.textContent = val;
    body.appendChild(nm);
    body.appendChild(v);
    step.appendChild(no);
    step.appendChild(body);
    wrap.appendChild(step);
  });
  return wrap;
}

function openDrawer(row, field) {
  $("drawer-title").textContent = `${row.title} · ${FIELD_LABEL[field]}`;
  const body = $("drawer-body");
  body.innerHTML = "";
  const summary = document.createElement("p");
  summary.textContent = row.fields[field] || "（无摘要）";
  body.appendChild(summary);
  const quotes = (row.claims || []).filter((c) => c.field === field);
  if (!quotes.length) body.appendChild(note("该字段没有通过校验的证据句。"));
  quotes.forEach((c) => {
    const q = document.createElement("div");
    q.className = "quote";
    q.appendChild(buildAudit(c));
    const src = document.createElement("div");
    src.className = "src";
    src.textContent = `第 ${c.page} 页 · ${LEVEL_LABEL[c.match_level] || c.match_level} · ${c.evidence_level === "fulltext" ? "全文证据" : "摘要级证据"}`;
    q.appendChild(src);
    if (c.entailment) {
      const pill = document.createElement("span");
      pill.className = "pill " + c.entailment;
      pill.textContent = { supported: "支持", partial: "部分支持", unsupported: "不支持" }[c.entailment] || c.entailment;
      q.appendChild(pill);
    }
    const txt = document.createElement("div");
    txt.textContent = "“" + c.quote + "”";
    q.appendChild(txt);
    if (c.reason) {
      const reason = document.createElement("div");
      reason.className = "src";
      reason.textContent = "判定理由：" + c.reason;
      q.appendChild(reason);
    }
    if (c.context) {
      const ctxBtn = document.createElement("button");
      ctxBtn.className = "ghost ctx-toggle";
      ctxBtn.textContent = "查看上下文";
      const ctxBox = document.createElement("div");
      ctxBox.className = "ctx hidden";
      const idx = c.context.indexOf(c.quote);
      if (idx >= 0) {
        ctxBox.appendChild(document.createTextNode(c.context.slice(0, idx)));
        const mark = document.createElement("mark");
        mark.className = "ctx-mark";
        mark.textContent = c.context.slice(idx, idx + c.quote.length);
        ctxBox.appendChild(mark);
        ctxBox.appendChild(document.createTextNode(c.context.slice(idx + c.quote.length)));
      } else {
        ctxBox.textContent = c.context;
      }
      ctxBtn.onclick = () => {
        const hidden = ctxBox.classList.toggle("hidden");
        ctxBtn.textContent = hidden ? "查看上下文" : "收起上下文";
      };
      q.appendChild(ctxBtn);
      q.appendChild(ctxBox);
    }
    if (row.paper_id && c.page) {
      const pdfLink = document.createElement("a");
      pdfLink.className = "pdf-link";
      pdfLink.href = "/api/pdf/" + encodeURIComponent(row.paper_id) + "#page=" + c.page;
      pdfLink.target = "_blank";
      pdfLink.rel = "noopener";
      pdfLink.textContent = "打开原文 PDF（第 " + c.page + " 页）";
      q.appendChild(pdfLink);
    }
    body.appendChild(q);
  });
  $("drawer").classList.remove("hidden");
  $("mask").classList.remove("hidden");
}

function note(text) {
  const p = document.createElement("p");
  p.className = "src";
  p.textContent = text;
  return p;
}

function closeDrawer() {
  $("drawer").classList.add("hidden");
  $("mask").classList.add("hidden");
}

async function loadLocal() {
  setStatus("加载本地 PDF…");
  try {
    const data = await api("/api/local");
    papers = data.papers || [];
    selected = new Set(papers.slice(0, 5).map((p) => p.id));
    page = 1;
    renderResults();
    setStatus(`本地共 ${papers.length} 篇，勾选要分析的论文`);
  } catch (e) {
    setStatus(e.message, true);
  }
}

async function uploadPdfs() {
  const files = $("file-input").files;
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  setStatus("上传中…");
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error("上传失败 " + r.status);
    const data = await r.json();
    papers = papers.concat(data.papers || []);
    (data.papers || []).forEach((p) => selected.add(p.id));
    renderResults();
    const errs = data.errors || [];
    if (errs.length) {
      setStatus(`已上传 ${(data.papers || []).length} 篇；以下文件被拒绝：${errs.join("；")}`, true);
    } else {
      setStatus(`已上传 ${(data.papers || []).length} 篇`);
    }
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("file-input").value = "";
  }
}

async function loadDemo() {
  setStatus("加载离线缓存…");
  try {
    const data = await api("/api/demo");
    if (data.error) { setStatus(data.error, true); return; }
    matrix = data;
    currentJobId = "demo";
    renderMatrix();
    setStatus("已加载离线演示缓存");
  } catch (e) {
    setStatus(e.message, true);
  }
}

function toggleAll() {
  const list = filteredPapers();
  const allSelected = list.every((p) => selected.has(p.id));
  list.forEach((p) => { allSelected ? selected.delete(p.id) : selected.add(p.id); });
  renderResults();
}

function renderExamples() {
  const box = $("examples");
  box.innerHTML = "";
  const hint = document.createElement("span");
  hint.className = "hint";
  hint.textContent = "试试：";
  box.appendChild(hint);
  EXAMPLES.forEach((q) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.textContent = q;
    chip.onclick = () => { $("query").value = q; search(); };
    box.appendChild(chip);
  });
}

function debouncedReSearch() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    if (searched && $("query").value.trim()) search();
  }, 300);
}

document.querySelectorAll(".export-row button").forEach((b) => {
  b.onclick = () => { if (matrix && currentJobId) window.location = "/api/export?format=" + b.dataset.fmt + "&job_id=" + encodeURIComponent(currentJobId); };
});
$("search-btn").onclick = search;
$("local-btn").onclick = loadLocal;
$("upload-btn").onclick = () => $("file-input").click();
$("file-input").onchange = uploadPdfs;
$("demo-btn").onclick = loadDemo;
$("toggle-all").onclick = toggleAll;
$("analyze-btn").onclick = analyze;
$("drawer-close").onclick = closeDrawer;
$("mask").onclick = closeDrawer;
$("theme-btn").onclick = toggleTheme;
$("query").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
$("limit").addEventListener("change", () => {
  $("custom-limit").classList.toggle("hidden", $("limit").value !== "custom");
  debouncedReSearch();
});
$("sort").addEventListener("change", debouncedReSearch);
$("custom-limit").addEventListener("change", () => {
  if ($("limit").value === "custom") debouncedReSearch();
});
$("fulltext-only").addEventListener("change", () => { page = 1; renderResults(); });

renderExamples();
applyTheme();
health();
