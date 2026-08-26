const COLORS = {
  user: "#7dd3fc",
  agent: "#c4b5fd",
  pack: "#f9a8d4",
  service_principal: "#86efac",
  connector: "#fdba74",
  resource: "#fca5a5",
  organization: "#94a3b8",
};

const decisionEl = document.getElementById("decision");
const sideEl = document.getElementById("side");
const svg = document.getElementById("graph");
const scenariosEl = document.getElementById("scenarios");

let graphData = { nodes: [], edges: [] };
let lastPath = [];

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function renderDecision(result, title) {
  decisionEl.className = `decision ${result.decision}`;
  const reasons = (result.reasons || []).map((r) => `<li>${r}</li>`).join("");
  const obligations = (result.obligations || [])
    .map((o) => `<li>${o.type}: ${JSON.stringify(o)}</li>`)
    .join("");
  decisionEl.innerHTML = `
    <div class="badge ${result.decision}">${result.decision}</div>
    <div><strong>${title || ""}</strong></div>
    <p>${result.reason}</p>
    <p>风险 ${result.risk_level || "-"} · 包 ${result.pack_id || "-"} · 审计 ${result.audit_id || "-"}</p>
    <ul>${reasons}</ul>
    ${obligations ? `<p>义务</p><ul>${obligations}</ul>` : ""}
  `;
  lastPath = result.path || [];
  drawGraph();
}

function drawGraph() {
  const pathNodes = new Set();
  const pathEdges = new Set();
  for (const step of lastPath) {
    if (step.agent) pathNodes.add(step.agent);
    if (step.caller && step.agent) pathEdges.add(`${step.caller}->${step.agent}`);
    if (step.sp) pathNodes.add(step.sp);
    if (step.resource) pathNodes.add(step.resource);
  }
  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const edgeLines = edges
    .map((e) => {
      const a = byId[e.from];
      const b = byId[e.to];
      if (!a || !b) return "";
      const hot = pathEdges.has(`${e.from}->${e.to}`) || (pathNodes.has(e.from) && pathNodes.has(e.to));
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${hot ? "#6ea8ff" : "#334155"}" stroke-width="${hot ? 2.4 : 1}" marker-end="url(#arrow)" />
        <text class="edge-label" x="${mx}" y="${my - 6}">${e.relation || ""}</text>`;
    })
    .join("");
  const nodeCircles = nodes
    .map((n) => {
      const color = COLORS[n.kind] || "#94a3b8";
      const hot = pathNodes.has(n.id);
      const dim = n.status === "offboarded";
      return `<g>
        <circle cx="${n.x}" cy="${n.y}" r="${hot ? 16 : 12}" fill="${color}" opacity="${dim ? 0.35 : 0.95}" stroke="${hot ? "#fff" : "transparent"}" />
        <text class="node-label" x="${n.x + 16}" y="${n.y + 4}">${n.label}</text>
      </g>`;
    })
    .join("");
  svg.innerHTML = `
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
      </marker>
    </defs>
    ${edgeLines}${nodeCircles}
  `;
}

async function refreshGraph() {
  graphData = await api("/api/graph");
  drawGraph();
}

async function loadScenarios() {
  const data = await api("/api/scenarios");
  scenariosEl.innerHTML = "";
  for (const s of data.scenarios) {
    const btn = document.createElement("button");
    btn.textContent = s.title;
    btn.onclick = async () => {
      const result = await api("/api/evaluate", { method: "POST", body: JSON.stringify(s.request) });
      renderDecision(result, s.title);
      await refreshAudit();
    };
    scenariosEl.appendChild(btn);
  }
}

async function refreshAudit() {
  const [audit, blast] = await Promise.all([
    api("/api/audit?limit=8"),
    api("/api/blast-radius?node=user:zhangsan"),
  ]);
  sideEl.textContent = JSON.stringify(
    {
      zhangsan_blast_radius: blast,
      recent_audit: audit.events.map((e) => ({
        id: e.id,
        decision: e.decision,
        initiator: e.initiator,
        actor: e.actor,
        action: e.action,
        resource: e.resource,
        reason: e.payload?.reason,
      })),
    },
    null,
    2
  );
}

document.getElementById("eval-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const chain = String(fd.get("chain") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const body = {
    initiator_human_id: fd.get("initiator_human_id"),
    actor_agent_id: fd.get("actor_agent_id"),
    action: fd.get("action"),
    resource_id: fd.get("resource_id"),
    data_owner_id: fd.get("data_owner_id") || null,
    amount: fd.get("amount") ? Number(fd.get("amount")) : null,
    delegation_chain: chain,
    pack_id: fd.get("pack_id"),
  };
  const result = await api("/api/evaluate", { method: "POST", body: JSON.stringify(body) });
  renderDecision(result, "自定义 evaluate");
  await refreshAudit();
};

document.getElementById("btn-reset").onclick = async () => {
  await api("/api/reset", { method: "POST", body: "{}" });
  lastPath = [];
  await refreshGraph();
  await refreshAudit();
  decisionEl.className = "decision empty";
  decisionEl.textContent = "演示数据已重置";
};

document.getElementById("btn-share").onclick = async () => {
  await api("/api/share", { method: "POST", body: JSON.stringify({ owner_id: "lisi", viewer_id: "zhangsan" }) });
  const result = await api("/api/evaluate", {
    method: "POST",
    body: JSON.stringify({
      initiator_human_id: "zhangsan",
      actor_agent_id: "erp-docs",
      action: "query",
      resource_id: "expense-api",
      data_owner_id: "lisi",
      document_id: "lisi-expense-doc",
      delegation_chain: ["expense-orchestrator", "invoice-ocr", "erp-docs"],
      pack_id: "expense-orch",
    }),
  });
  renderDecision(result, "分享后张三查询李四单据");
  await refreshGraph();
  await refreshAudit();
};

document.getElementById("btn-offboard").onclick = async () => {
  const info = await api("/api/offboard/zhangsan", { method: "POST", body: "{}" });
  sideEl.textContent = JSON.stringify(info, null, 2);
  const result = await api("/api/evaluate", {
    method: "POST",
    body: JSON.stringify({
      initiator_human_id: "zhangsan",
      actor_agent_id: "erp-docs",
      action: "submit",
      resource_id: "expense-api",
      amount: 1200,
      delegation_chain: ["expense-orchestrator", "invoice-ocr", "erp-docs"],
    }),
  });
  renderDecision(result, "张三离职后再次提交");
  await refreshGraph();
};

document.getElementById("btn-lisi").onclick = async () => {
  const result = await api("/api/evaluate", {
    method: "POST",
    body: JSON.stringify({
      initiator_human_id: "lisi",
      actor_agent_id: "erp-docs",
      action: "submit",
      resource_id: "expense-api",
      amount: 900,
      delegation_chain: ["expense-orchestrator", "invoice-ocr", "erp-docs"],
    }),
  });
  renderDecision(result, "李四提交本人报销");
  await refreshAudit();
};

document.getElementById("btn-approve").onclick = async () => {
  const req = {
    initiator_human_id: "zhangsan",
    actor_agent_id: "erp-docs",
    action: "submit",
    resource_id: "expense-api",
    amount: 8000,
    delegation_chain: ["expense-orchestrator", "invoice-ocr", "erp-docs"],
    pack_id: "expense-orch",
  };
  const token = await api("/api/approvals", { method: "POST", body: JSON.stringify(req) });
  const result = await api("/api/evaluate", {
    method: "POST",
    body: JSON.stringify({ ...req, obligation_tokens: [token.id] }),
  });
  renderDecision(result, "持有审批票据后提交 8000");
  await refreshAudit();
};

(async function init() {
  try {
    const h = await api("/api/health");
    document.getElementById("health").textContent = h.engine;
    await loadScenarios();
    await refreshGraph();
    await refreshAudit();
  } catch (err) {
    document.getElementById("health").textContent = "error";
    sideEl.textContent = String(err);
  }
})();
