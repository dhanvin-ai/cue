/* Cue teammate console — talks to the FastAPI backend over /v1/tenants/{tenant}/... */
(() => {
  "use strict";

  const TENANT = window.__CUE_TENANT__;
  const UID = window.__CUE_UID__;

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const pretty = (value) =>
    typeof value === "string" ? value : JSON.stringify(value, null, 2);

  function whenVisible(callback) {
    if (document.visibilityState === "visible") callback();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") callback();
    });
  }

  /* ---------------------------------------------------------------- api ---- */
  async function api(path, options = {}) {
    const response = await fetch(`/v1/tenants/${TENANT}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const type = response.headers.get("content-type") || "";
    if (!type.includes("json")) {
      const text = await response.text();
      if (!response.ok) throw new Error(describe(response.status, text));
      return text;
    }
    const body = await response.json();
    if (!response.ok) throw new Error(describe(response.status, body.detail));
    return body;
  }

  // FastAPI reports most failures as {detail}; a 500 from an unhandled error
  // does not, so say what the status means instead of showing nothing.
  function describe(status, detail) {
    const clean = typeof detail === "string" ? detail : JSON.stringify(detail)
    if (clean && clean !== "undefined") return `${status}: ${clean}`;
    const fallback = {
      401: "Not signed in — the dev auth bypass is off, so this page cannot authenticate.",
      403: "Your role is not allowed to do this.",
      404: "Not found.",
      500: "The server failed handling this request. Check the API log; agent answers and memory queries need a working model gateway.",
    };
    return `${status}: ${fallback[status] || "Request failed."}`;
  }

  /* -------------------------------------------------------------- config -- */
  // The runtime needs an inference endpoint and a worker. Both are read from
  // the live API rather than assumed, so the banner never lies about status.
  const Runtime = {
    gateway: false,
    gatewayUrl: window.__CUE_GATEWAY_URL__ || "",
    gatewayKey: Boolean(window.__CUE_GATEWAY_KEY__),
    workerIdleSeconds: 90,
  };

  const TIERS = [
    { tier: 0, name: "read", mode: "auto", note: "Runs freely inside the asker's permissions." },
    { tier: 1, name: "internal reversible", mode: "auto", note: "Runs automatically and is logged." },
    { tier: 2, name: "internal visible", mode: "approve", note: "Needs one click of confirmation." },
    { tier: 3, name: "external", mode: "approve", note: "Always approved explicitly in v1." },
    { tier: 4, name: "prohibited", mode: "deny", note: "Never available to the agent." },
  ];

  const NAV = [
    { id: "ask", label: "Ask Cue", title: "Ask Cue", sub: "Send work to the agent runtime and watch it run.", icon: "M8 1h8a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4H7l-3 3v-9a4 4 0 0 1 4-4z" },
    { id: "approvals", label: "Approvals", title: "Approvals", sub: "Tier 2 and 3 actions waiting on a human decision.", badge: true, icon: "M12 2 4 5v6c0 5 3.4 8.6 8 11 4.6-2.4 8-6 8-11V5l-8-3zm-1 13-3.5-3.5 1.4-1.4L11 12.2l4.6-4.6 1.4 1.4L11 15z" },
    { id: "memory", label: "Memory", title: "Team memory", sub: "Permissioned retrieval across every connected source.", icon: "M12 3a9 9 0 0 0-9 9 9 9 0 0 0 4 7.5V21h10v-1.5A9 9 0 0 0 21 12a9 9 0 0 0-9-9z" },
    { id: "tasks", label: "Tasks", title: "Agent tasks", sub: "Every request the runtime has taken, newest first.", icon: "M4 4h16v5H4zM4 11h16v5H4zM4 18h10v3H4z" },
    { id: "meetings", label: "Meetings", title: "Meetings", sub: "Join by voice, then read the notes Cue writes afterwards.", icon: "M12 3a4 4 0 0 1 4 4v4a4 4 0 0 1-8 0V7a4 4 0 0 1 4-4zm7 8a7 7 0 0 1-6 6.9V22h-2v-4.1A7 7 0 0 1 5 11h2a5 5 0 0 0 10 0h2z" },
    { id: "proactive", label: "Proactive", title: "Proactive work", sub: "Digests, reminders and follow-ups Cue runs on a schedule.", icon: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 10.6 4 2.3-1 1.7-5-2.9V6h2v6.6z" },
    { id: "admin", label: "Admin", title: "Tenant admin", sub: "Status, controls, access report and audit trail.", icon: "M12 2 3 6v6c0 5 3.8 9.4 9 10 5.2-.6 9-5 9-10V6l-9-4zm0 6a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zm0 8c1.9 0 3.6-.7 4.8-1.9-.9-1.4-2.8-2.1-4.8-2.1s-3.9.7-4.8 2.1A5.8 5.8 0 0 0 12 16z" },
  ];

  const state = { view: "ask", role: "member", tasks: [], polls: new Map() };

  /* --------------------------------------------------------------- shell --- */
  function buildNav() {
    const nav = $("nav");
    for (const item of NAV) {
      const button = el("button", "nav-item");
      button.dataset.pane = item.id;
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.setAttribute("fill", "currentColor");
      svg.appendChild(el("path"));
      svg.firstChild.setAttribute("d", item.icon);
      button.append(svg, el("span", null, item.label));
      if (item.badge) button.appendChild(el("span", "badge", "0"));
      button.onclick = () => show(item.id);
      nav.appendChild(button);
    }
  }

  function show(id) {
    state.view = id;
    const item = NAV.find((entry) => entry.id === id);
    for (const node of document.querySelectorAll(".nav-item"))
      node.classList.toggle("active", node.dataset.pane === id);
    for (const pane of document.querySelectorAll(".pane"))
      pane.classList.toggle("active", pane.dataset.pane === id);
    $("viewTitle").textContent = item.title;
    $("viewSub").textContent = item.sub;
    renderRuntimeBanner();
    if (id === "approvals") loadApprovals();
    if (id === "tasks") loadTasks();
    if (id === "proactive") loadProactive();
    if (id === "admin") loadAdmin();
  }

  function setDot(dotId, textId, level, text) {
    $(dotId).className = `dot ${level}`;
    $(textId).textContent = text;
  }

  function renderRuntimeBanner() {
    const holder = $("runtimeBanner");
    holder.textContent = "";
    const problems = [];
    if (!Runtime.gatewayUrl)
      problems.push({ level: "bad", text: "MODEL_GATEWAY_BASE_URL is not set, so the agent cannot plan or answer. Point it at an OpenAI-compatible endpoint." });
    else if (!Runtime.gatewayKey)
      problems.push({ level: "warn", text: `Model gateway is configured (${Runtime.gatewayUrl}) but no API key is loaded, so inference calls will be rejected. Set MODEL_GATEWAY_API_KEY in .env.` });
    if (state.workerStale)
      problems.push({ level: "warn", text: "Tasks are sitting queued with no worker picking them up. Run `python scripts/run_tasks.py` to execute them." });
    for (const problem of problems) holder.appendChild(el("div", `banner ${problem.level}`, problem.text));
  }

  async function checkRuntime() {
    try {
      const health = await fetch("/healthz").then((r) => r.json());
      setDot("apiDot", "apiText", health.status === "ok" ? "ok" : "warn", health.status);
    } catch {
      setDot("apiDot", "apiText", "bad", "unreachable");
      return;
    }
    // The browser cannot test inference: the gateway needs the server-side API
    // key and sends no CORS headers. Report what the server was configured with.
    Runtime.gateway = Boolean(Runtime.gatewayUrl && Runtime.gatewayKey);
    renderRuntimeBanner();
  }

  /* ---------------------------------------------------------------- ask ---- */
  function citationBlock(citations) {
    const box = el("div", "cite-list");
    box.appendChild(el("div", "hint", `${citations.length} source${citations.length === 1 ? "" : "s"}`));
    for (const cite of citations) {
      const line = el("div", "cite");
      line.append(el("span", "src", `[${cite.number}] ${cite.source || cite.summary_start || ""} ${cite.type || ""}`));
      if (cite.url) {
        line.append(document.createTextNode(" — "));
        line.appendChild(el("a", null, "open source")).setAttribute("href", cite.url);
        line.lastChild.target = "_blank";
      }
      const body = (cite.text || "").slice(0, 260);
      if (body) line.appendChild(el("div", null, body));
      box.appendChild(line);
    }
    return box;
  }

  function taskBubble(task) {
    const bubble = el("div", "bubble agent");
    bubble.dataset.taskId = task.task_id;
    const meta = el("div", "meta");
    meta.append(el("span", `pill ${task.status}`, task.status));
    meta.append(el("span", null, `${task.source} · ${task.task_id.slice(0, 8)} · attempt ${task.attempts}`));
    const body = el("div", "txt");
    bubble.append(meta, body);
    const planBox = el("div");
    bubble.appendChild(planBox);
    const errBox = el("div", "err");
    errBox.hidden = true;
    bubble.appendChild(errBox);
    const approvalBox = el("div");
    bubble.appendChild(approvalBox);
    bubble._render = () => paintTask(bubble, task);
    paintTask(bubble, task);
    return bubble;
  }

  // A queued task that already carries a dispatch stamp was handed to a worker
  // that never reported back, so no scheduler tick will offer it again.
  function isStranded(task) {
    if (task.status !== "queued" || !task.dispatched_at) return false;
    return Date.now() - new Date(task.dispatched_at).getTime() > 60_000;
  }

  function paintTask(bubble, task) {
    bubble.dataset.task = JSON.stringify(task);
    const pill = bubble.querySelector(".pill");
    pill.className = `pill ${task.status}`;
    pill.textContent = task.status;
    bubble.querySelector(".meta span:nth-child(2)").textContent =
      `${task.source} · ${task.task_id.slice(0, 8)} · attempt ${task.attempts}`;
    const body = bubble.querySelector(".txt");
    body.textContent = task.answer || task.request_text || "";
    const planBox = bubble.children[3];
    planBox.textContent = "";
    if (task.plan && (task.plan.tool_calls || []).length) {
      const details = el("details");
      details.appendChild(el("summary", null, `planned ${task.plan.tool_calls.length} tool call(s) · ${task.plan.provider || ""}`));
      const list = el("pre");
      list.textContent = pretty(task.plan.tool_calls);
      details.appendChild(list);
      planBox.appendChild(details);
    }
    const errBox = bubble.querySelector(".err");
    errBox.hidden = !task.error;
    errBox.textContent = task.error || "";
    const approvalBox = bubble.children[4];
    if (isStranded(task)) {
      const notice = el("div", "banner warn", "Dispatched but not executed — the worker may have been stopped.");
      const retry = el("button", "btn ghost small", "Requeue task");
      retry.style.marginLeft = "8px";
      retry.onclick = async () => {
        retry.disabled = true;
        try {
          await api(`/agent/tasks/${task.task_id}/requeue`, { method: "POST" });
          refreshTask(task.task_id);
          pollTask(task.task_id);
        } catch (error) {
          retry.disabled = false;
          flashError(error.message);
        }
      };
      notice.appendChild(retry);
      approvalBox.replaceChildren(notice);
      return;
    }
    renderApprovalRows(approvalBox, task.approvals || [], () => refreshTask(task.task_id));
  }

  function renderApprovalRows(holder, approvals, onChange) {
    if (!holder) return;
    holder.textContent = "";
    for (const approval of approvals) {
      const row = el("div", "row");
      row.style.marginTop = "8px";
      row.append(el("span", `pill ${approval.status}`, approval.status));
      row.append(el("code", null, approval.tool));
      row.append(el("span", "hint", `tier ${approval.tier}`));
      if (approval.status === "pending") {
        for (const [label, cls, approve] of [["Approve", "btn ok small", true], ["Reject", "btn danger small", false]]) {
          const button = el("button", cls, label);
          button.onclick = async () => {
            button.disabled = true;
            await decide(approval.id, approve);
            onChange();
          };
          row.appendChild(button);
        }
      }
      holder.appendChild(row);
      if (Object.keys(approval.arguments || {}).length) {
        const args = el("pre");
        args.style.maxHeight = "140px";
        args.textContent = pretty(approval.arguments);
        holder.appendChild(args);
      }
    }
  }

  async function decide(approvalId, approve) {
    try {
      await api(`/agent/approvals/${approvalId}`, {
        method: "POST", body: JSON.stringify({ approve }),
      });
    } catch (error) {
      flashError(error.message);
    }
  }

  function stopPoll(taskId) {
    const timer = state.polls.get(taskId);
    if (timer) { clearTimeout(timer); state.polls.delete(taskId); }
  }

  function pollTask(taskId) {
    stopPoll(taskId);
    const timer = setTimeout(async () => {
      if (!state.polls.has(taskId)) return;
      const task = await refreshTask(taskId);
      if (task && ["queued", "running", "awaiting_approval"].includes(task.status)) pollTask(taskId);
      else stopPoll(taskId);
    }, 2500);
    state.polls.set(taskId, timer);
  }

  async function refreshTask(taskId) {
    const bubble = document.querySelector(`.bubble[data-task-id="${taskId}"]`);
    let task;
    try {
      task = await api(`/agent/tasks/${taskId}`);
    } catch (error) {
      if (bubble) { const box = bubble.querySelector(".err"); box.hidden = false; box.textContent = error.message; }
      stopPoll(taskId);
      return null;
    }
    if (bubble) paintTask(bubble, task);
    detectWorker(task);
    return task;
  }

  // A task that leaves the queue proves a worker is alive; one parked in the
  // queue past a deadline proves there is none. No invented endpoint needed.
  function detectWorker(task) {
    if (["running", "completed", "failed", "cancelled", "awaiting_approval"].includes(task.status)) {
      state.workerStale = false;
      setDot("workerDot", "workerText", "ok", "running");
      renderRuntimeBanner();
    }
  }

  function markWorkerStale(tasks) {
    const active = tasks.filter((t) => t.status !== "queued");
    if (active.length) { state.workerStale = false; setDot("workerDot", "workerText", "ok", "running"); return; }
    const oldest = tasks.find((t) => t.status === "queued");
    if (!oldest) { setDot("workerDot", "workerText", "idle", "idle"); return; }
    const age = (Date.now() - new Date(oldest.created_at).getTime()) / 1000;
    const stale = age > Runtime.workerIdleSeconds;
    state.workerStale = stale;
    setDot("workerDot", "workerText", stale ? "warn" : "idle", stale ? "no worker" : "idle");
  }

  function userBubble(text) {
    const bubble = el("div", "bubble me");
    const meta = el("div", "meta");
    meta.append(el("span", null, UID), el("span", null, "just now"));
    bubble.append(meta, el("div", "txt", text));
    return bubble;
  }

  async function sendRequest() {
    const text = $("askInput").value.trim();
    if (!text) return;
    $("askBtn").disabled = true;
    try {
      const created = await api("/agent/requests", {
        method: "POST", body: JSON.stringify({ text, request_id: crypto.randomUUID() }),
      });
      ensureThreadHasContent();
      $("thread").appendChild(userBubble(text));
      const bubble = taskBubble({ ...created, request_text: text, attempts: 0, approvals: [] });
      $("thread").appendChild(bubble);
      bubble.scrollIntoView({ behavior: "smooth", block: "end" });
      pollTask(created.task_id);
      $("askInput").value = "";
    } catch (error) {
      flashError(error.message);
    } finally {
      $("askBtn").disabled = false;
    }
  }

  async function loadThread() {
    const holder = $("thread");
    holder.textContent = "";
    let tasks;
    try {
      ({ tasks } = await api("/agent/tasks?limit=30"));
    } catch (error) {
      holder.appendChild(el("div", "err", error.message));
      return;
    }
    markWorkerStale(tasks);
    renderRuntimeBanner();
    if (!tasks.length) { holder.appendChild(el("div", "empty", "No requests yet. Ask Cue something above.")); return; }
    for (const task of [...tasks].reverse()) {
      if (task.request_text) holder.appendChild(userBubble(task.request_text));
      holder.appendChild(taskBubble(task));
      if (["queued", "running", "awaiting_approval"].includes(task.status)) pollTask(task.task_id);
    }
  }

  // Sending a request must clear the placeholder left by an empty history.
  function ensureThreadHasContent() {
    const holder = $("thread");
    const placeholder = holder.querySelector(".empty");
    if (placeholder) placeholder.remove();
  }

  function flashError(message) {
    const banner = el("div", "banner bad", message);
    $("runtimeBanner").prepend(banner);
    setTimeout(() => banner.remove(), 6000);
  }

  /* ---------------------------------------------------------- approvals -- */
  async function loadApprovals() {
    const holder = $("approvalsList");
    holder.textContent = "";
    let approvals;
    try {
      ({ approvals } = await api("/agent/approvals"));
    } catch (error) {
      holder.appendChild(el("div", "err", error.message));
      return;
    }
    const badge = document.querySelector('.nav-item[data-pane="approvals"] .badge');
    badge.textContent = approvals.length;
    badge.classList.toggle("show", approvals.length > 0);
    if (!approvals.length) { holder.appendChild(el("div", "empty", "Nothing is waiting on you.")); return; }
    for (const approval of approvals) {
      const card = el("div", "card");
      card.style.background = "var(--surface-2)";
      const head = el("div", "row");
      head.append(el("span", `pill ${approval.task_status}`, approval.task_status));
      head.append(el("code", null, approval.tool));
      head.append(el("span", "hint", `tier ${approval.tier} · ${approval.source} · ${timeAgo(approval.created_at)}`));
      card.appendChild(head);
      if (approval.request_text) card.appendChild(el("div", "hint", `“${approval.request_text.slice(0, 200)}”`));
      const args = el("pre");
      args.textContent = pretty(approval.arguments);
      card.appendChild(args);
      const actions = el("div", "row");
      actions.style.marginTop = "8px";
      for (const [label, cls, approve] of [["Approve & continue", "btn ok", true], ["Reject", "btn danger", false]]) {
        const button = el("button", cls, label);
        button.onclick = async () => {
          button.disabled = true;
          await decide(approval.id, approve);
          loadApprovals();
        };
        actions.appendChild(button);
      }
      const open = el("button", "btn ghost small", "Open task");
      open.onclick = () => { show("tasks"); setTimeout(loadTaskDetail.bind(null, approval.task_id), 50); };
      actions.appendChild(open);
      card.appendChild(actions);
      holder.appendChild(card);
    }
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    return `${Math.round(seconds / 86400)}d ago`;
  }

  /* ------------------------------------------------------------- memory -- */
  async function queryMemory() {
    const question = $("memInput").value.trim();
    if (!question) return;
    const holder = $("memOut");
    $("memBtn").disabled = true;
    holder.textContent = "";
    holder.appendChild(el("div", "hint", "Routing the question…"));
    try {
      const result = await api("/memory/query", {
        method: "POST", body: JSON.stringify({ question }),
      });
      holder.textContent = "";
      const card = el("div", "card");
      card.style.background = "var(--surface-2)";
      const head = el("div", "row");
      head.append(el("span", "pill completed", `route: ${result.route}`));
      card.appendChild(head);
      card.appendChild(el("div", "txt", result.answer || "No answer returned."));
      if ((result.citations || []).length) card.appendChild(citationBlock(result.citations));
      holder.appendChild(card);
    } catch (error) {
      holder.textContent = "";
      holder.appendChild(el("div", "banner bad", error.message));
    } finally {
      $("memBtn").disabled = false;
    }
  }

  /* -------------------------------------------------------------- tasks --- */
  async function loadTasks() {
    const holder = $("tasksTable");
    holder.textContent = "";
    const status = $("taskFilter").value;
    let tasks;
    try {
      ({ tasks } = await api(`/agent/tasks?limit=50${status ? `&status=${status}` : ""}`));
    } catch (error) {
      holder.appendChild(el("div", "err", error.message));
      return;
    }
    markWorkerStale(tasks);
    renderRuntimeBanner();
    if (!tasks.length) { holder.appendChild(el("div", "empty", "No tasks match.")); return; }
    const table = el("table");
    const headRow = el("tr");
    for (const label of ["Task", "Status", "Requested", "Answer / error", "Updated"])
      headRow.appendChild(el("th", null, label));
    table.append(el("thead", null, ""), el("tbody"));
    table.firstChild.appendChild(headRow);
    for (const task of tasks) {
      const row = el("tr");
      row.style.cursor = "pointer";
      row.append(
        el("td", null, `${task.task_id.slice(0, 8)} (${task.source})`),
        el("td", null, ""),
        el("td", null, (task.request_text || "").slice(0, 90)),
        el("td", null, (task.answer || task.error || "—").slice(0, 120)),
        el("td", "hint", timeAgo(task.updated_at)),
      );
      row.children[1].appendChild(el("span", `pill ${task.status}`, task.status));
      row.onclick = () => loadTaskDetail(task.task_id);
      table.lastChild.appendChild(row);
    }
    holder.appendChild(table);
  }

  async function loadTaskDetail(taskId) {
    let task;
    try {
      task = await api(`/agent/tasks/${taskId}`);
    } catch (error) {
      flashError(error.message);
      return;
    }
    const holder = $("tasksTable");
    const card = el("div", "card");
    card.style.border = "1px solid var(--accent)";
    const head = el("div", "row");
    head.append(el("span", `pill ${task.status}`, task.status), el("code", null, task.task_id));
    const close = el("button", "btn ghost small", "Close");
    close.onclick = loadTasks;
    head.append(el("div", "spacer"), close);
    card.appendChild(head);
    card.appendChild(el("div", "divider"));
    card.appendChild(el("div", "hint", `asked: ${task.request_text || "—"}`));
    card.appendChild(el("div", null, task.answer || task.error || "(no answer yet)"));
    if (task.plan) {
      const pre = el("pre");
      pre.textContent = pretty(task.plan);
      card.appendChild(pre);
    }
    const approvalBox = el("div");
    card.appendChild(approvalBox);
    renderApprovalRows(approvalBox, task.approvals || [], () => loadTaskDetail(taskId));
    holder.prepend(card);
  }

  /* ----------------------------------------------------------- meetings --- */
  async function joinMeeting() {
    const meeting_url = $("mtUrl").value.trim();
    if (!meeting_url) return flashError("A meeting URL is required.");
    const attendees = $("mtPeople").value.split("\n").map((line) => line.trim()).filter(Boolean)
      .map((email) => ({ email, display_name: email.split("@")[0] }));
    const holder = $("mtOut");
    $("mtJoin").disabled = true;
    holder.textContent = "";
    try {
      const result = await api("/meetings", {
        method: "POST",
        body: JSON.stringify({ meeting_url, title: $("mtTitle").value.trim() || null, attendees }),
      });
      holder.appendChild(el("div", "banner", `Joined as ${result.bot_id}. Disclosure sent: ${result.disclosure}`));
      $("ntId").value = result.meeting_id;
      const pre = el("pre");
      pre.textContent = pretty(result);
      holder.appendChild(pre);
    } catch (error) {
      holder.appendChild(el("div", "banner bad", error.message));
    } finally {
      $("mtJoin").disabled = false;
    }
  }

  async function loadNotes() {
    const meetingId = $("ntId").value.trim();
    if (!meetingId) return flashError("Enter a meeting ID.");
    const holder = $("ntOut");
    holder.textContent = "";
    try {
      const note = await api(`/meetings/${meetingId}/notes`);
      renderNote(holder, note.note || note);
    } catch (error) {
      holder.appendChild(el("div", "banner bad", error.message));
    }
  }

  function renderNote(holder, note) {
    if (!note) { holder.appendChild(el("div", "empty", "No notes yet.")); return; }
    const card = el("div", "card");
    card.style.background = "var(--surface-2)";
    card.appendChild(el("h2", null, "Summary"));
    card.appendChild(el("div", null, note.summary || "—"));
    if ((note.decisions || []).length) {
      card.appendChild(el("div", "divider"));
      card.appendChild(el("h2", null, "Decisions"));
      const list = el("ul");
      for (const decision of note.decisions) list.appendChild(el("li", null, decision));
      card.appendChild(list);
    }
    if ((note.action_items || []).length) {
      card.appendChild(el("div", "divider"));
      card.appendChild(el("h2", null, "Action items"));
      const list = el("ul");
      for (const item of note.action_items)
        list.appendChild(el("li", null, `${item.text || item}${item.owner ? ` — ${item.owner}` : ""}${item.due ? ` (due ${item.due})` : ""}`));
      card.appendChild(list);
    }
    if ((note.sources || []).length) {
      card.appendChild(el("div", "divider"));
      card.appendChild(el("h2", null, "Transcript sources"));
      for (const source of note.sources)
        card.appendChild(el("div", "cite", `[${source.position ?? source}] ${typeof source === "string" ? source : source.quote || ""}`));
    }
    card.appendChild(el("div", "hint", `visibility: ${note.visibility || "—"} · ${note.published_at ? "published" : "not published"}`));
    holder.appendChild(card);
  }

  async function endMeeting() {
    const meetingId = $("ntId").value.trim();
    if (!meetingId) return flashError("Enter a meeting ID.");
    const holder = $("ntOut");
    $("ntEnd").disabled = true;
    holder.textContent = "";
    try {
      const result = await api(`/meetings/${meetingId}/end`, { method: "POST" });
      renderNote(holder, result.note);
      if ((result.actions || []).length) {
        const pre = el("pre");
        pre.textContent = pretty(result.actions);
        holder.appendChild(pre);
      }
    } catch (error) {
      holder.appendChild(el("div", "banner bad", error.message));
    } finally {
      $("ntEnd").disabled = false;
    }
  }

  /* ---------------------------------------------------------- proactive --- */
  async function loadProactive() {
    const holder = $("ruleList");
    holder.textContent = "";
    let view;
    try {
      view = await api("/proactive");
    } catch (error) {
      holder.appendChild(el("div", "err", error.message));
      return;
    }
    if (!view.rules.length) holder.appendChild(el("div", "empty", "No rules scheduled."));
    const table = el("table");
    const headRow = el("tr");
    for (const label of ["Key", "Kind", "Schedule", "Next run", "Last run", "Enabled"])
      headRow.appendChild(el("th", null, label));
    table.append(el("thead"), el("tbody"));
    table.firstChild.appendChild(headRow);
    for (const rule of view.rules) {
      const row = el("tr");
      row.append(
        el("td", null, rule.rule_key),
        el("td", null, rule.kind),
        el("td", "mono", rule.schedule || "one-shot"),
        el("td", "hint", rule.next_run_at ? new Date(rule.next_run_at).toLocaleString() : "—"),
        el("td", "hint", rule.last_run_at ? timeAgo(rule.last_run_at) : "never"),
        el("td", null, ""),
      );
      row.children[5].appendChild(el("span", `pill ${rule.enabled ? "active" : "skipped"}`, rule.enabled ? "yes" : "no"));
      table.lastChild.appendChild(row);
    }
    if (view.rules.length) holder.appendChild(table);

    const muteBox = $("muteList");
    muteBox.textContent = "";
    const lines = [];
    if (view.mutes.length) lines.push(...view.mutes.map((m) => `muted: ${m.firebase_uid} → ${m.rule_key}`));
    if (view.quiet_hours.length) lines.push(...view.quiet_hours.map((q) => `quiet hours (${q.scope} ${q.subject}): ${q.start_time}–${q.end_time} ${q.timezone}`));
    if (!lines.length) muteBox.appendChild(el("div", "empty", "No mutes or quiet hours set."));
    for (const line of lines) muteBox.appendChild(el("div", "hint", line));

    const runBox = $("runList");
    runBox.textContent = "";
    if (!view.runs.length) { runBox.appendChild(el("div", "empty", "No runs yet.")); return; }
    const runTable = el("table");
    const runHead = el("tr");
    for (const label of ["Rule", "Status", "Deliver after", "Created"]) runHead.appendChild(el("th", null, label));
    runTable.append(el("thead"), el("tbody"));
    runTable.firstChild.appendChild(runHead);
    for (const run of view.runs) {
      const row = el("tr");
      row.append(
        el("td", null, run.rule_key),
        el("td", null, ""),
        el("td", "hint", run.deliver_after ? new Date(run.deliver_after).toLocaleString() : "—"),
        el("td", "hint", timeAgo(run.created_at)),
      );
      row.children[1].appendChild(el("span", `pill ${run.status}`, run.status));
      runTable.lastChild.appendChild(row);
    }
    runBox.appendChild(runTable);
  }

  async function createRule() {
    const body = {
      rule_key: $("prKey").value.trim(),
      kind: $("prKind").value,
      timezone: $("prTz").value.trim() || "UTC",
    };
    if (!$("prKey").value.trim()) return flashError("Rule key is required.");
    if ($("prSchedule").value.trim()) body.schedule = $("prSchedule").value.trim();
    if ($("prNext").value.trim()) body.next_run_at = new Date($("prNext").value).toISOString();
    const rawConfig = $("prConfig").value.trim();
    if (rawConfig) {
      try { body.config = JSON.parse(rawConfig); }
      catch { return flashError("Config must be valid JSON."); }
    }
    try {
      await api("/proactive/rules", { method: "POST", body: JSON.stringify(body) });
      $("prOut").textContent = "";
      $("prOut").appendChild(el("div", "banner", "Rule created."));
      loadProactive();
    } catch (error) {
      $("prOut").textContent = "";
      $("prOut").appendChild(el("div", "banner bad", error.message));
    }
  }

  async function saveQuietHours() {
    try {
      const scope = $("qhScope").value;
      await api("/admin/quiet-hours", {
        method: "PUT",
        body: JSON.stringify({
          scope, subject: scope === "user" ? UID : "*",
          timezone: $("qhTz").value.trim() || "UTC",
          start: $("qhStart").value, end: $("qhEnd").value,
        }),
      });
      loadProactive();
    } catch (error) { flashError(error.message); }
  }

  /* -------------------------------------------------------------- admin --- */
  async function loadAdmin() {
    let status;
    try {
      status = await api("/status");
    } catch (error) {
      $("statusStats").textContent = "";
      $("statusStats").appendChild(el("div", "err", error.message));
      return;
    }
    const stats = $("statusStats");
    stats.textContent = "";
    const counts = status.tasks || {};
    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
    const tiles = [
      ["Tasks", total],
      ["Awaiting approval", status.pending_approvals],
      ["Completed", counts.completed || 0],
      ["Failed", counts.failed || 0],
      ["Queued", counts.queued || 0],
      ["Paused events buffered", status.paused_events],
    ];
    for (const [label, value] of tiles) {
      const tile = el("div", "stat");
      tile.append(el("div", "lbl", label), el("div", "num", value));
      stats.appendChild(tile);
    }
    const extra = [];
    if (status.connectors?.length)
      extra.push(status.connectors.map((c) => `${c.provider}: ${c.status} ×${c.count}`).join(" · "));
    else extra.push("No connectors linked to this tenant yet.");
    if (status.paused?.length) extra.push(`PAUSED: ${status.paused.map((p) => `${p.scope} ${p.subject} (${p.mode})`).join(", ")}`);
    if (status.deferred_proactive) extra.push(`${status.deferred_proactive} proactive run(s) deferred to quiet hours.`);
    if (status.last_reconciliation)
      extra.push(`Reconciliation ${status.last_reconciliation.status} · missing ${status.last_reconciliation.missing} · backfilled ${status.last_reconciliation.backfilled}`);
    extra.push(`Checked ${new Date(status.checked_at).toLocaleTimeString()}`);
    $("statusExtra").textContent = extra.join("  ·  ");

    let switches;
    try {
      ({ switches } = await api("/admin/kill-switches"));
    } catch (error) {
      switches = [];
      $("switchList").appendChild(el("div", "err", error.message));
    }
    const box = $("switchList");
    box.textContent = "";
    if (!switches.length) box.appendChild(el("div", "empty", "No kill switches recorded."));
    for (const item of switches) {
      const row = el("div", "row");
      row.append(
        el("span", `pill ${item.paused ? "paused" : "active"}`, item.paused ? "paused" : "active"),
        el("code", null, `${item.scope}/${item.subject}`),
        el("span", "hint", `${item.mode}${item.reason ? ` · ${item.reason}` : ""}${item.changed_by ? ` · by ${item.changed_by}` : ""}`),
      );
      box.appendChild(row);
    }

    const tiers = $("tierList");
    tiers.textContent = "";
    for (const tier of TIERS) {
      const row = el("div", "row");
      row.style.justifyContent = "space-between";
      row.append(
        el("span", null, `Tier ${tier.tier} · ${tier.name}`),
        el("span", `pill ${tier.mode === "auto" ? "completed" : tier.mode === "deny" ? "failed" : "awaiting_approval"}`, tier.mode),
      );
      row.title = tier.note;
      tiers.appendChild(row);
      tiers.appendChild(el("div", "hint", tier.note));
    }
  }

  async function setSwitch(paused) {
    const scope = $("ksScope").value;
    const subject = encodeURIComponent($("ksSubject").value.trim() || "*");
    try {
      await api(`/admin/kill-switches/${scope}/${subject}`, {
        method: "PUT",
        body: JSON.stringify(paused
          ? { paused: true, mode: $("ksMode").value, reason: "paused from console" }
          : { paused: false }),
      });
      loadAdmin();
    } catch (error) { flashError(error.message); }
  }

  async function loadAccessReport() {
    const holder = $("accessReport");
    holder.textContent = "";
    let report;
    try {
      report = await api("/admin/access-report");
    } catch (error) {
      holder.appendChild(el("div", "err", error.message));
      return;
    }
    const grid = el("div", "grid three");
    for (const [label, value] of [
      ["Documents", report.can_read.totals.documents],
      ["Graph edges", report.can_read.totals.edges],
      ["Summaries", report.can_read.totals.summaries],
      ["Meetings", report.can_read.totals.meetings],
      ["Notes", report.can_read.totals.notes],
      ["Members", report.users.length],
    ]) {
      const tile = el("div", "stat");
      tile.append(el("div", "lbl", label), el("div", "num", value));
      grid.appendChild(tile);
    }
    holder.appendChild(grid);

    const sections = [
      ["Users", report.users.map((u) => `${u.firebase_uid} (${u.role})${u.revoked_at ? " REVOKED" : ""} · ${u.principals.length} principal(s)`)],
      ["Connectors", report.connectors.map((c) => `${c.provider} ${c.external_id} — ${c.status}${c.paused ? " PAUSED" : ""}${c.last_error ? ` · ${c.last_error}` : ""}`)],
      ["Policies", report.policies.map((p) => `${p.scope}/${p.subject} → ${p.mode}`)],
      ["Revocations", report.revocations.map((r) => `${r.kind} ${r.subject} — ${r.reason}`)],
      ["Memory by source", report.can_read.by_source.map((d) => `${d.source} / ${d.visibility}: ${d.count}`)],
    ];
    for (const [title, lines] of sections) {
      if (!lines.length) continue;
      const details = el("details");
      details.appendChild(el("summary", null, `${title} (${lines.length})`));
      const list = el("div");
      for (const line of lines) list.appendChild(el("div", "hint", line));
      details.appendChild(list);
      holder.appendChild(details);
    }
  }

  async function exportAudit() {
    const since = $("auSince").value, until = $("auUntil").value;
    if (!since || !until) return flashError("Pick a start and end time.");
    const format = $("auFormat").value;
    const url = `/v1/tenants/${TENANT}/admin/audit/export?since=${encodeURIComponent(new Date(since).toISOString())}` +
      `&until=${encodeURIComponent(new Date(until).toISOString())}&format=${format}`;
    const holder = $("auditOut");
    holder.textContent = "";
    try {
      const response = await fetch(url);
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail.slice(0, 300));
      }
      const text = await response.text();
      const download = el("button", "btn ghost small", "Download");
      download.onclick = () => {
        const blob = new Blob([text], { type: format === "csv" ? "text/csv" : "application/json" });
        const link = el("a");
        link.href = URL.createObjectURL(blob);
        link.download = `cue-audit.${format}`;
        link.click();
        URL.revokeObjectURL(link.href);
      };
      const pre = el("pre");
      pre.textContent = format === "json" ? pretty(JSON.parse(text)) : text;
      holder.append(download, pre);
    } catch (error) {
      holder.appendChild(el("div", "banner bad", error.message));
    }
  }

  async function revokeAccess() {
    const subject = $("rvSubject").value.trim();
    const reason = $("rvReason").value.trim();
    if (!subject || !reason) return flashError("Subject and reason are both required.");
    try {
      await api("/admin/revocations", {
        method: "POST",
        body: JSON.stringify({ kind: $("rvKind").value, subject, reason }),
      });
      $("dangerOut").textContent = "";
      $("dangerOut").appendChild(el("div", "banner", "Revocation propagated across stores."));
      loadAdmin();
      loadAccessReport();
    } catch (error) {
      $("dangerOut").textContent = "";
      $("dangerOut").appendChild(el("div", "banner bad", error.message));
    }
  }

  async function deleteEvent() {
    const eventId = $("evId").value.trim();
    if (!eventId) return flashError("Enter an event id.");
    if (!confirm(`Delete ${eventId} from every store? This cannot be undone from the UI.`)) return;
    try {
      const result = await api(`/admin/events/${encodeURIComponent(eventId)}`, { method: "DELETE" });
      $("dangerOut").textContent = "";
      const pre = el("pre");
      pre.textContent = pretty(result);
      $("dangerOut").append(el("div", "banner", "Deleted."), pre);
    } catch (error) {
      $("dangerOut").textContent = "";
      $("dangerOut").appendChild(el("div", "banner bad", error.message));
    }
  }

  /* --------------------------------------------------------------- init --- */
  function wire() {
    $("askBtn").onclick = sendRequest;
    $("reloadThread").onclick = loadThread;
    $("askInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) sendRequest();
    });
    $("memBtn").onclick = queryMemory;
    $("memInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) queryMemory();
    });
    $("tasksRefresh").onclick = loadTasks;
    $("taskFilter").onchange = loadTasks;
    $("mtJoin").onclick = joinMeeting;
    $("ntLoad").onclick = loadNotes;
    $("ntEnd").onclick = endMeeting;
    $("prCreate").onclick = createRule;
    $("qhSave").onclick = saveQuietHours;
    $("ksPause").onclick = () => setSwitch(true);
    $("ksResume").onclick = () => setSwitch(false);
    $("arLoad").onclick = loadAccessReport;
    $("auLoad").onclick = exportAudit;
    $("rvRun").onclick = revokeAccess;
    $("evDelete").onclick = deleteEvent;
    $("refreshBtn").onclick = () => {
      checkRuntime();
      if (state.view === "ask") loadThread();
      else if (state.view === "approvals") loadApprovals();
      else if (state.view === "tasks") loadTasks();
      else if (state.view === "proactive") loadProactive();
      else if (state.view === "admin") { loadAdmin(); loadAccessReport(); }
    };
    const now = new Date();
    $("auUntil").value = localIso(now);
    $("auSince").value = localIso(new Date(now.getTime() - 24 * 3600 * 1000));
  }

  const localIso = (date) =>
    new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

  async function boot() {
    buildNav();
    wire();
    show("ask");
    $("who").textContent = UID;
    $("tenantLabel").textContent = TENANT.slice(0, 8) + "…";
    try {
      const me = await api("/me");
      state.role = me.role;
      $("roleLabel").textContent = me.role;
      for (const id of ["approvals", "admin"])
        document.querySelector(`.nav-item[data-pane="${id}"]`).style.display =
          id === "admin" && me.role !== "admin" ? "none" : "";
    } catch (error) {
      $("roleLabel").textContent = "unknown";
      flashError(error.message);
    }
    await loadThread();
    checkRuntime();
    setInterval(checkRuntime, 15000);
    whenVisible(loadApprovals);
    setInterval(() => { if (state.view === "approvals") loadApprovals(); }, 20000);
  }

  boot();
})();
