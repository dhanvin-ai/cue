/* Cue console: meetings, chat, memory, activity and settings over /v1/tenants/{tenant}/... */
(() => {
  "use strict";

  const TENANT = window.__CUE_TENANT__;
  const UID = window.__CUE_UID__ || "";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  /* ---------------------------------------------------------------- icons -- */
  // One stroke family for every glyph, so the rail, sources and settings read as a set.
  const PATHS = {
    meetings: "M3 7a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 10l5-3v10l-5-3",
    chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
    memory: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
    activity: "M9 11l3 3 8-8M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
    settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
    github: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
    gmail: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM3 7l9 6 9-6",
    calendar: "M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM16 3v4M8 3v4M3 11h18",
    calendly: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
    meeting: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
    sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
    search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
    shield: "M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z",
    end: "M6 6l12 12M18 6L6 18",
    slack: "M9 3v18M15 3v18M3 9h18M3 15h18",
    jira: "M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4zM14 5v12",
    n8n: "M6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM9 12h3l3-6M12 12l3 6",
    zapier: "M13 2L4 14h7l-1 8 9-12h-7z",
    notion: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
    apollo: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
    asana: "M12 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 20a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 20a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", PATHS[name] || PATHS.sparkle);
    svg.appendChild(path);
    return svg;
  }
  const SOURCE_ICON = { github: "github", gmail: "gmail", calendar: "calendar", calendly: "calendly", meeting: "meeting" };
  const SOURCE_NAME = { github: "GitHub", gmail: "Gmail", calendar: "Calendar", calendly: "Calendly", meeting: "Meeting" };

  /* ------------------------------------------------------------------ api -- */
  async function api(path, options = {}) {
    const response = await fetch(`/v1/tenants/${TENANT}${path}`, {
      ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const body = (response.headers.get("content-type") || "").includes("json")
      ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof body === "object" ? body.detail : body;
      throw new Error(explain(response.status, detail));
    }
    return body;
  }

  function explain(status, detail) {
    if (typeof detail === "string" && detail && status !== 500) return detail;
    return {
      401: "You're signed out. The local console needs CUE_DEV_AUTH_UID set on the API.",
      403: "Your role doesn't allow that.",
      404: "That's no longer there.",
      500: "The server hit an error. Check the API log; answers need a working model gateway.",
    }[status] || `Request failed (${status}).`;
  }

  function toast(message, bad = false) {
    const node = el("div", `toast${bad ? " bad" : ""}`, message);
    $("toasts").appendChild(node);
    setTimeout(() => node.remove(), 5000);
  }

  // Answers arrive as light markdown with [n] citation marks; render bold, drop the marks.
  function prose(text, cls = "body") {
    const node = el("div", cls);
    const clean = String(text || "").replace(/\s*\[\d+(?:,\s*\d+)*\]/g, "").replace(/^\s*[-*]\s+/gm, "• ");
    clean.split(/\*\*(.+?)\*\*/g).forEach((part, i) => {
      node.appendChild(i % 2 ? el("strong", null, part) : document.createTextNode(part));
    });
    return node;
  }

  /* ---------------------------------------------------------------- time --- */
  function ago(iso) {
    if (!iso) return "";
    const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 45) return "just now";
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    if (s < 86400 * 7) return `${Math.round(s / 86400)}d ago`;
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function clock(iso, start) {
    if (!iso) return "";
    const s = Math.max(0, Math.round((new Date(iso) - new Date(start || iso)) / 1000));
    const pad = (n) => String(n).padStart(2, "0");
    return s >= 3600 ? `${Math.floor(s / 3600)}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`
      : `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
  }
  function stamp(iso) {
    return iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) : "";
  }

  /* ---------------------------------------------------------------- shell -- */
  const VIEWS = [
    { id: "meetings", label: "Meetings", sub: "What Cue heard and said in your calls." },
    { id: "chat", label: "Chat", sub: "Ask Cue outside a meeting." },
    { id: "memory", label: "Memory", sub: "Everything Cue can draw on, searchable." },
    { id: "activity", label: "Activity", sub: "Actions Cue took, and the ones waiting on you." },
    { id: "settings", label: "Settings", sub: "Accounts and how Cue behaves." },
  ];
  const state = { view: "meetings", meetings: [], meetingId: null, timer: null, mode: "agent", polls: new Map() };

  function buildRail() {
    for (const view of VIEWS) {
      const button = el("button", "rail-btn");
      button.dataset.view = view.id;
      button.setAttribute("aria-label", view.label);
      button.append(icon(view.id), el("span", "tip", view.label), el("span", "dot"));
      button.onclick = () => show(view.id);
      $("nav").appendChild(button);
    }
    $("me").textContent = (UID.replace(/[^a-z]/gi, "")[0] || "Y").toUpperCase();
    $("me").title = UID || "You";
  }

  function show(id) {
    state.view = id;
    const view = VIEWS.find((v) => v.id === id);
    for (const b of document.querySelectorAll(".rail-btn")) {
      b.classList.toggle("active", b.dataset.view === id);
      b.toggleAttribute("aria-current", b.dataset.view === id);
    }
    for (const v of document.querySelectorAll(".view")) v.classList.toggle("active", v.dataset.view === id);
    $("title").textContent = view.label;
    $("subtitle").textContent = view.sub;
    $("topActions").replaceChildren();
    try { localStorage.setItem("cue.view", id); } catch (_) { /* storage is optional */ }
    history.replaceState(null, "", `#${id}`);
    if (id === "meetings") { state.live = null; loadMeetings(); }
    else stopLive();
    if (id === "memory") $("memQ").focus();
    if (id === "chat") $("ask").focus();
    if (id === "activity") loadActivity();
    if (id === "settings") loadSettings();
  }

  /* ------------------------------------------------------------- meetings -- */
  const AVATAR_TONES = ["#5144d9", "#1f9fd6", "#d0567a", "#1f9a72", "#c9781b", "#7b4fd1"];
  function avatar(name, isCue) {
    const node = el("div", "avatar");
    if (isCue) {
      node.style.background = "#fff";
      const img = el("img");
      img.src = "/ui/mascot/idle.png";
      img.alt = "";
      node.appendChild(img);
      return node;
    }
    const label = (name || "?").trim();
    let hash = 0;
    for (const ch of label) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    node.style.background = AVATAR_TONES[hash % AVATAR_TONES.length];
    node.textContent = label.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
    return node;
  }

  function meetingTitle(m) {
    if (m.title) return m.title;
    const code = (m.meeting_url || "").split("/").pop();
    return code ? `Meet · ${code}` : "Untitled call";
  }

  async function loadMeetings() {
    let meetings;
    try {
      ({ meetings } = await api("/meetings"));
    } catch (error) {
      $("meetList").replaceChildren(el("div", "empty", error.message));
      return;
    }
    state.meetings = meetings;
    renderMeetingList();
    if (!state.meetingId || !meetings.some((m) => m.id === state.meetingId)) {
      const live = meetings.find((m) => m.status === "live") || meetings[0];
      state.meetingId = live ? live.id : null;
    }
    if (state.meetingId) openMeeting(state.meetingId);
    else renderWelcome();
  }

  function renderMeetingList() {
    const holder = $("meetList");
    holder.replaceChildren();
    const groups = [["Live now", (m) => m.status !== "ended"], ["Earlier", (m) => m.status === "ended"]];
    for (const [label, test] of groups) {
      const items = state.meetings.filter(test);
      if (!items.length) continue;
      holder.appendChild(el("h2", null, label));
      for (const m of items) {
        const item = el("button", `meet-item${m.id === state.meetingId ? " active" : ""}`);
        item.appendChild(el("span", "t", meetingTitle(m)));
        const meta = el("span", "m");
        if (m.status === "live") meta.appendChild(el("span", "tag live", "Live"));
        else if (m.status === "joining") meta.appendChild(el("span", "tag warn", "Waiting to be let in"));
        meta.appendChild(el("span", null,
          `${ago(m.started_at || m.created_at)} · ${m.replies} answer${m.replies === 1 ? "" : "s"}`));
        item.appendChild(meta);
        item.onclick = () => {
          if (m.id === state.meetingId) return;
          state.meetingId = m.id;
          state.live = null;
          renderMeetingList();
          openMeeting(m.id);
        };
        holder.appendChild(item);
      }
    }
  }

  function renderWelcome() {
    state.live = null;
    stopLive();
    const box = el("div", "welcome");
    const img = el("img", "art");
    img.src = "/ui/mascot/hero.png";
    img.alt = "";
    box.append(img, el("h2", null, "Bring Cue into your next call"),
      el("p", "muted", "Paste a Google Meet link on the left. Cue joins as a participant, listens, and answers when someone says “Hey Cue”."));
    $("stage").replaceChildren(box);
    $("side").replaceChildren(cueCard("idle", "Ready when you are", "Not in a call right now."));
  }

  function stopLive() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = null;
    if (state.inflight) state.inflight.abort();
    state.inflight = null;
  }

  const POLL_MS = 2000;

  // Polls the open meeting. One request at a time, none while the tab is hidden, and the
  // DOM is reconciled rather than rebuilt, so the transcript never flickers or loses scroll.
  async function openMeeting(id) {
    stopLive();
    if (state.live && state.live.id !== id) state.live = null;
    if (document.hidden) {
      state.timer = setTimeout(() => openMeeting(id), POLL_MS);
      return;
    }
    const controller = new AbortController();
    state.inflight = controller;
    let data;
    try {
      data = await api(`/meetings/${id}/timeline`, { signal: controller.signal });
    } catch (error) {
      if (error.name === "AbortError") return;
      if (!state.live) $("stage").replaceChildren(el("div", "empty", error.message));
      state.timer = setTimeout(() => openMeeting(id), POLL_MS * 2);
      return;
    } finally {
      if (state.inflight === controller) state.inflight = null;
    }
    if (id !== state.meetingId || state.view !== "meetings") return;
    renderStage(data.meeting, data.entries);
    if (data.meeting.status !== "ended") state.timer = setTimeout(() => openMeeting(id), POLL_MS);
  }

  // What Cue is doing right now, read from the shape of the conversation.
  function cueMood(meeting, entries) {
    if (meeting.status === "ended") return ["idle", "Off the call", "Notes are under the transcript."];
    if (meeting.status === "joining") return ["idle", "Waiting in the lobby", "Admit Cue from the Meet window."];
    const last = entries[entries.length - 1];
    const age = last ? (Date.now() - new Date(last.at).getTime()) / 1000 : Infinity;
    if (last && last.kind === "cue" && age < 12) return ["talking", "Answering out loud", "Sources are on the reply."];
    const asked = last && last.kind === "speech" && /\bcue\b|\?\s*$/i.test(last.text);
    if (asked && age < 20) return ["thinking", "Looking it up…", "Checking GitHub, email and calendar."];
    return ["idle", "Listening", "Say “Hey Cue” followed by a question."];
  }

  const entryKey = (e) => `${e.kind}|${e.at}|${e.speaker_id}|${e.text}`;
  const setText = (node, text) => { if (node.textContent !== String(text)) node.textContent = text; };

  // Builds the parts of the stage that only change when another meeting is opened or its
  // status changes; everything else is patched in place by renderStage.
  function buildStage(meeting) {
    const actions = $("topActions");
    actions.replaceChildren();
    if (meeting.status !== "ended") {
      const end = el("button", "btn", "End & write notes");
      end.prepend(icon("end"));
      end.onclick = () => endMeeting(meeting.id, end);
      actions.appendChild(end);
    }
    const head = el("div", "stage-head");
    head.appendChild(el("h2", null, meetingTitle(meeting)));
    if (meeting.status === "live") head.appendChild(el("span", "tag live", "Live"));
    if (meeting.status === "joining") head.appendChild(el("span", "tag warn", "Waiting to be let in"));
    if (meeting.status === "ended") head.appendChild(el("span", "tag", "Ended"));
    const list = el("div", "transcript");
    list.setAttribute("aria-live", "polite");
    const empty = el("div", "empty", meeting.status === "ended"
      ? "Nothing was said while Cue was in this call." : "Captions will appear here as people talk.");
    list.appendChild(empty);
    $("stage").replaceChildren(head, list);
    if (meeting.status === "ended") $("stage").appendChild(notesBlock(meeting.id));

    const card = el("div", "cue-card");
    const poseBox = el("div", "pose");
    const poses = {};
    for (const name of ["idle", "thinking", "talking"]) {
      const img = el("img", "art");
      img.src = `/ui/mascot/${name}.png`;
      img.alt = "";
      poses[name] = img;
      poseBox.appendChild(img);
    }
    const headline = el("div", "state");
    const sub = el("div", "state-sub");
    card.append(poseBox, headline, sub);
    const facts = el("dl", "facts");
    const fact = {};
    for (const [key, label] of [["started", "Started"], ["duration", "Duration"],
      ["people", "People heard"], ["answers", "Questions answered"]]) {
      const row = el("div");
      fact[key] = el("span");
      row.append(el("dt", null, label), fact[key]);
      facts.appendChild(row);
    }
    $("side").replaceChildren(card, facts);
    return { id: meeting.id, status: meeting.status, list, empty, nodes: new Map(), keys: [],
      poses, pose: null, headline, sub, fact, painted: false };
  }

  function lineNode(entry, start, fresh) {
    const isCue = entry.kind === "cue";
    const line = el("div", `line${isCue ? " cue" : ""}${fresh ? " fresh" : ""}`);
    const body = el("div");
    body.append(el("div", "who", isCue ? "Cue" : entry.speaker), el("div", "said", entry.text));
    line.append(avatar(entry.speaker, isCue), body, el("div", "at", clock(entry.at, start)));
    return line;
  }

  function renderStage(meeting, entries) {
    let live = state.live;
    if (!live || live.id !== meeting.id || live.status !== meeting.status) {
      live = state.live = buildStage(meeting);
    }
    const { list } = live;
    const start = meeting.started_at || (entries[0] && entries[0].at);
    const keys = entries.map(entryKey);
    const changed = keys.length !== live.keys.length || keys.some((k, i) => k !== live.keys[i]);

    if (changed) {
      const pinned = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
      const wanted = new Set(keys);
      for (const [key, node] of live.nodes) {
        if (!wanted.has(key)) { node.remove(); live.nodes.delete(key); }
      }
      live.empty.hidden = entries.length > 0;
      // Walk in order: reuse each line, create only new ones, and move a node only when a
      // late caption landed before it.
      let cursor = live.empty.nextSibling;
      entries.forEach((entry, index) => {
        const key = keys[index];
        let node = live.nodes.get(key);
        if (!node) {
          node = lineNode(entry, start, live.painted);
          live.nodes.set(key, node);
        }
        if (node !== cursor) list.insertBefore(node, cursor);
        else cursor = cursor.nextSibling;
        node.classList.toggle("old", index < entries.length - 6);
        const who = node.querySelector(".who");
        const asked = entry.kind === "speech" && /\bcue\b/i.test(entry.text)
          && entries[index + 1] && entries[index + 1].kind === "cue";
        const mark = who.querySelector(".ask-mark");
        if (asked && !mark) who.appendChild(el("span", "ask-mark", "asked Cue"));
        if (!asked && mark) mark.remove();
      });
      live.keys = keys;
      if (pinned || !live.painted) list.scrollTop = list.scrollHeight;
    }
    live.painted = true;

    // The mood depends on the clock as well as the entries, so it is re-read every poll.
    const [pose, headline, sub] = cueMood(meeting, entries);
    if (pose !== live.pose) {
      for (const [name, img] of Object.entries(live.poses)) {
        img.classList.toggle("on", name === pose);
        img.alt = name === pose ? `Cue: ${headline}` : "";
      }
      live.pose = pose;
    }
    setText(live.headline, headline);
    setText(live.sub, sub);
    setText(live.fact.started, meeting.started_at ? stamp(meeting.started_at) : "Not yet");
    setText(live.fact.duration, entries.length ? clock(entries[entries.length - 1].at, start) : "00:00");
    setText(live.fact.people, new Set(entries.filter((e) => e.kind === "speech").map((e) => e.speaker)).size);
    setText(live.fact.answers, entries.filter((e) => e.kind === "cue").length);
  }

  function notesBlock(meetingId) {
    const box = el("div", "notes");
    box.appendChild(el("p", "muted", "Loading notes…"));
    api(`/meetings/${meetingId}/notes`).then((data) => {
      const note = data.note || data;
      box.replaceChildren();
      box.appendChild(el("h4", null, "Summary"));
      box.appendChild(el("p", null, note.summary || "No summary."));
      if ((note.decisions || []).length) {
        box.appendChild(el("h4", null, "Decisions"));
        const ul = el("ul");
        for (const d of note.decisions) ul.appendChild(el("li", null, typeof d === "string" ? d : d.text));
        box.appendChild(ul);
      }
      if ((note.action_items || []).length) {
        box.appendChild(el("h4", null, "Action items"));
        const ul = el("ul");
        for (const item of note.action_items) {
          const li = el("li", null, item.text || item);
          const extra = [item.owner, item.due && `due ${item.due}`].filter(Boolean).join(" · ");
          if (extra) li.appendChild(el("small", null, extra));
          ul.appendChild(li);
        }
        box.appendChild(ul);
      }
    }).catch(() => {
      box.replaceChildren(el("p", "muted", "No notes for this meeting yet."));
    });
    return box;
  }

  async function joinMeeting(event) {
    event.preventDefault();
    let url = $("joinUrl").value.trim();
    if (!url) return;
    if (!/^https?:\/\//.test(url)) url = `https://${url}`;
    $("joinBtn").disabled = true;
    $("joinBtn").textContent = "Sending…";
    try {
      const result = await api("/meetings", {
        method: "POST",
        body: JSON.stringify({ meeting_url: url, title: $("joinTitle").value.trim() || null, voice: "attendee" }),
      });
      toast("Cue is on its way. Admit it from the Meet window.");
      $("joinUrl").value = "";
      $("joinTitle").value = "";
      state.meetingId = result.meeting_id;
      loadMeetings();
    } catch (error) {
      toast(error.message, true);
    } finally {
      $("joinBtn").disabled = false;
      $("joinBtn").textContent = "Send Cue";
    }
  }

  async function endMeeting(id, button) {
    button.disabled = true;
    button.lastChild.textContent = "Writing notes…";
    try {
      await api(`/meetings/${id}/end`, { method: "POST" });
      toast("Cue left the call and wrote the notes.");
      loadMeetings();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
      button.lastChild.textContent = "End & write notes";
    }
  }

  /* ----------------------------------------------------------------- chat -- */
  const STARTS = [
    { q: "What changed in the repo this week?", s: "GitHub", i: "github" },
    { q: "Anything in my inbox I should know about?", s: "Gmail", i: "gmail" },
    { q: "What did we decide in the last meeting?", s: "Meetings", i: "meeting" },
  ];
  const MODES = [
    { id: "agent", label: "Ask Cue", i: "sparkle", hint: "Ask about commits, issues, email, meetings…" },
    { id: "memory", label: "Search memory", i: "search", hint: "Search what Cue has read, with sources…" },
  ];

  function buildChat() {
    for (const start of STARTS) {
      const card = el("button", "start");
      const top = el("div");
      top.appendChild(icon(start.i));
      const text = el("div");
      text.append(el("div", "q", start.q), el("div", "s", start.s));
      card.append(top, text);
      card.onclick = () => { $("ask").value = start.q; send(); };
      $("starts").appendChild(card);
    }
    for (const mode of MODES) {
      const chip = el("button", `chip${mode.id === state.mode ? " on" : ""}`, mode.label);
      chip.type = "button";
      chip.prepend(icon(mode.i));
      chip.setAttribute("aria-pressed", mode.id === state.mode);
      chip.onclick = () => {
        state.mode = mode.id;
        for (const c of $("modeChips").children) {
          const on = c === chip;
          c.classList.toggle("on", on);
          c.setAttribute("aria-pressed", on);
        }
        $("ask").placeholder = mode.hint;
        $("ask").focus();
      };
      $("modeChips").appendChild(chip);
    }
    const box = $("ask");
    box.addEventListener("input", () => {
      box.style.height = "auto";
      box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
      $("sendBtn").disabled = !box.value.trim();
    });
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    });
    $("composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
  }

  function cueMessage() {
    const msg = el("div", "msg cue");
    msg.appendChild(avatar("Cue", true));
    const body = el("div");
    const status = el("div", "status");
    const dots = el("span", "typing");
    dots.append(el("i"), el("i"), el("i"));
    status.append(dots, el("span", null, "Thinking…"));
    body.appendChild(status);
    msg.appendChild(body);
    return { msg, body };
  }

  function sourceChips(citations) {
    const row = el("div", "sources");
    for (const cite of citations.slice(0, 6)) {
      const chip = el(cite.url ? "a" : "span", "source");
      if (cite.url) { chip.href = cite.url; chip.target = "_blank"; chip.rel = "noopener"; }
      chip.append(el("b", null, cite.number), el("span", null,
        `${SOURCE_NAME[cite.source] || cite.source || "Source"} · ${(cite.text || "").replace(/\s+/g, " ").slice(0, 60)}`));
      chip.title = cite.text || "";
      row.appendChild(chip);
    }
    return row;
  }

  function scrollChat() {
    const s = $("chatScroll");
    s.scrollTop = s.scrollHeight;
  }

  async function send() {
    const box = $("ask");
    const text = box.value.trim();
    if (!text) return;
    $("hello").hidden = true;
    box.value = "";
    box.style.height = "auto";
    $("sendBtn").disabled = true;
    const mine = el("div", "msg me");
    mine.appendChild(el("div", "body", text));
    const { msg, body } = cueMessage();
    $("thread").append(mine, msg);
    scrollChat();
    try {
      if (state.mode === "memory") {
        const result = await api("/memory/query", { method: "POST", body: JSON.stringify({ question: text }) });
        body.replaceChildren(prose(result.answer || result.summary || "I couldn't find anything on that."));
        if ((result.citations || []).length) body.appendChild(sourceChips(result.citations));
      } else {
        const created = await api("/agent/requests", {
          method: "POST", body: JSON.stringify({ text, request_id: crypto.randomUUID() }),
        });
        followTask(created.task_id, body);
      }
    } catch (error) {
      body.replaceChildren(el("div", "body", error.message));
    }
    scrollChat();
  }

  function followTask(taskId, body) {
    const tick = async () => {
      let task;
      try {
        task = await api(`/agent/tasks/${taskId}`);
      } catch (error) {
        body.replaceChildren(el("div", "body", error.message));
        return;
      }
      paintTask(task, body);
      if (["queued", "running", "awaiting_approval"].includes(task.status)) setTimeout(tick, 1500);
    };
    tick();
  }

  function paintTask(task, body) {
    const working = { queued: "Picking this up…", running: "Working on it…" }[task.status];
    if (working) {
      body.querySelector(".status span:last-child").textContent = working;
      return;
    }
    body.replaceChildren();
    if (task.status === "awaiting_approval") {
      const pending = (task.approvals || []).filter((a) => a.status === "pending");
      body.appendChild(el("div", "body", task.answer || "I need your go-ahead before I do this."));
      for (const approval of pending) body.appendChild(inlineApproval(approval, () => followTask(task.task_id, body)));
    } else if (task.status === "failed") {
      body.appendChild(el("div", "body", task.error ? `That didn't work: ${task.error}` : "That didn't work."));
    } else {
      body.appendChild(prose(task.answer || "Done."));
      const cites = task.plan && (task.plan.citations || (task.plan.memory || {}).citations);
      if (cites && cites.length) body.appendChild(sourceChips(cites));
    }
    scrollChat();
  }

  function inlineApproval(approval, after) {
    const row = el("div", "inline-approval");
    row.appendChild(el("span", null, `Wants to run ${humanTool(approval.tool)}`));
    const yes = el("button", "btn ok small", "Approve");
    const no = el("button", "btn light small", "Decline");
    yes.onclick = async () => { await decide(approval.id, true); after(); };
    no.onclick = async () => { await decide(approval.id, false); after(); };
    row.append(yes, no);
    return row;
  }

  /* --------------------------------------------------------------- memory -- */
  const MEM_FILTERS = [
    ["Latest commits", "github", "What are the latest commits?"],
    ["Open issues", "github", "What issues are open?"],
    ["New email", "gmail", "What are the latest emails?"],
    ["This week's calendar", "calendar", "What's on the calendar this week?"],
  ];

  function buildMemory() {
    for (const [label, src, q] of MEM_FILTERS) {
      const chip = el("button", "chip", label);
      chip.type = "button";
      chip.prepend(icon(SOURCE_ICON[src]));
      chip.onclick = () => { $("memQ").value = q; searchMemory(); };
      $("memChips").appendChild(chip);
    }
    $("memForm").addEventListener("submit", (e) => { e.preventDefault(); searchMemory(); });
  }

  async function searchMemory() {
    const question = $("memQ").value.trim();
    if (question.length < 3) return;
    const out = $("memOut");
    $("memBtn").disabled = true;
    out.replaceChildren(el("p", "muted", "Searching…"));
    try {
      const result = await api("/memory/query", { method: "POST", body: JSON.stringify({ question }) });
      out.replaceChildren();
      const answer = el("div", "answer");
      answer.appendChild(prose(result.answer || result.summary || "Nothing found.", "p"));
      out.appendChild(answer);
      const records = el("div", "records");
      for (const cite of result.citations || []) {
        const row = el("div", "record");
        const ico = el("div", "ico");
        ico.appendChild(icon(SOURCE_ICON[cite.source] || "sparkle"));
        const mid = el("div");
        mid.appendChild(el("div", "txt", (cite.text || "").slice(0, 320)));
        const meta = el("div", "meta", `${SOURCE_NAME[cite.source] || cite.source} · ${(cite.type || "").replace(/[._]/g, " ")}`);
        if (cite.url) {
          meta.append(" · ");
          const link = el("a", null, "Open");
          link.href = cite.url; link.target = "_blank"; link.rel = "noopener";
          meta.appendChild(link);
        }
        mid.appendChild(meta);
        row.append(ico, mid, el("div", "when", ago(cite.occurred_at)));
        records.appendChild(row);
      }
      if (!(result.citations || []).length) records.appendChild(el("div", "empty", "No matching records. Try naming the source: “commits”, “emails”, “calendar”."));
      out.appendChild(records);
    } catch (error) {
      out.replaceChildren(el("div", "empty", error.message));
    } finally {
      $("memBtn").disabled = false;
    }
  }

  /* ------------------------------------------------------------- activity -- */
  const TOOL_WORDS = {
    "github.create_issue": "Create a GitHub issue", "github.comment": "Comment on GitHub",
    "gmail.send": "Send an email", "gmail.send_email": "Send an email", "gmail.draft": "Draft an email",
    "calendar.create_event": "Create a calendar event", "calendly.create_link": "Create a Calendly link",
  };
  function humanTool(tool) {
    return TOOL_WORDS[tool] || tool.replace(/^\w+\./, "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  }

  async function decide(id, approve) {
    try {
      await api(`/agent/approvals/${id}`, { method: "POST", body: JSON.stringify({ approve }) });
      toast(approve ? "Approved. Cue is on it." : "Declined. Nothing was changed.");
    } catch (error) {
      toast(error.message, true);
    }
    refreshBadge();
  }

  async function refreshBadge() {
    try {
      const { approvals } = await api("/agent/approvals");
      document.querySelector('.rail-btn[data-view="activity"] .dot').classList.toggle("show", approvals.length > 0);
      return approvals;
    } catch (_) {
      return null;
    }
  }

  async function loadActivity() {
    const approvals = await refreshBadge();
    const holder = $("approvals");
    holder.replaceChildren();
    const hero = el("div", "act-hero");
    const img = el("img", "art");
    img.alt = "";
    const words = el("div");
    if (approvals && approvals.length) {
      img.src = "/ui/mascot/approval.png";
      words.append(el("h2", null, `${approvals.length} thing${approvals.length === 1 ? "" : "s"} waiting on you`),
        el("p", "muted", "Cue won't touch other tools until you say yes."));
    } else {
      img.src = "/ui/mascot/acting.png";
      words.append(el("h2", null, "All clear"), el("p", "muted", "Nothing is waiting for approval."));
    }
    hero.append(img, words);
    holder.appendChild(hero);
    for (const a of approvals || []) {
      const card = el("div", "approval");
      const ico = el("div", "ico");
      ico.appendChild(icon("shield"));
      const body = el("div");
      body.appendChild(el("h2", null, humanTool(a.tool)));
      body.appendChild(el("div", "why", `${a.request_text ? `Because someone asked: “${a.request_text.slice(0, 140)}”` : "Requested by Cue"} · ${ago(a.created_at)}`));
      const args = el("dl", "args");
      for (const [k, v] of Object.entries(a.arguments || {})) {
        args.append(el("dt", null, k.replace(/_/g, " ")), el("dd", null, typeof v === "string" ? v : JSON.stringify(v)));
      }
      if (args.children.length) body.appendChild(args);
      const actions = el("div", "actions");
      const yes = el("button", "btn ok", "Approve");
      const no = el("button", "btn light", "Decline");
      yes.onclick = async () => { yes.disabled = no.disabled = true; await decide(a.id, true); loadActivity(); };
      no.onclick = async () => { yes.disabled = no.disabled = true; await decide(a.id, false); loadActivity(); };
      actions.append(yes, no);
      body.appendChild(actions);
      card.append(ico, body);
      holder.appendChild(card);
    }

    const history = $("history");
    try {
      const { tasks } = await api("/agent/tasks?limit=25");
      history.replaceChildren();
      if (!tasks.length) history.appendChild(el("div", "empty", "Cue hasn't done anything yet."));
      for (const t of tasks) {
        const row = el("div", "task-row");
        row.appendChild(el("span", `pip ${t.status}`));
        const mid = el("div");
        mid.appendChild(el("div", "q", t.request_text || "(no request text)"));
        const a = (t.answer || t.error || "").replace(/\s*\[\d+(?:,\s*\d+)*\]/g, "");
        if (a) mid.appendChild(el("div", "a", a));
        row.append(mid, el("span", "muted", `${t.source} · ${ago(t.updated_at)}`));
        history.appendChild(row);
      }
    } catch (error) {
      history.replaceChildren(el("div", "empty", error.message));
    }
  }

  /* ------------------------------------------------------------- settings -- */
  const ACCOUNTS = [
    ["github", "GitHub", "Commits, pull requests and issues"],
    ["gmail", "Gmail", "Email threads"],
    ["calendar", "Google Calendar", "Events and attendees"],
    ["calendly", "Calendly", "Bookings and scheduling links"],
  ];
  // Not built yet: shown so the team can see what's planned, never as connectable.
  const PLANNED = [
    ["slack", "Slack", "Channels, threads and decisions"],
    ["jira", "Jira", "Tickets, sprints and assignees"],
    ["notion", "Notion", "Docs, specs and wikis"],
    ["asana", "Asana", "Projects and tasks"],
    ["apollo", "Apollo", "Contacts and accounts"],
    ["zapier", "Zapier", "Trigger your Zaps from a meeting"],
    ["n8n", "n8n", "Run your workflows from a meeting"],
  ];
  const TIERS = [
    [0, "Read and search", "Automatic", "ok"],
    [1, "Internal and reversible", "Automatic, logged", "ok"],
    [2, "Visible to the team", "Needs approval", "warn"],
    [3, "Leaves the company", "Needs approval", "warn"],
    [4, "Prohibited", "Never", "bad"],
  ];

  async function loadSettings() {
    const holder = $("connectors");
    let status = null;
    try { status = await api("/status"); } catch (error) { toast(error.message, true); }
    holder.replaceChildren();
    const by = {};
    for (const c of (status && status.connectors) || []) (by[c.provider] = by[c.provider] || []).push(c);
    for (const [id, name, what] of ACCOUNTS) {
      const row = el("div", "conn");
      const ico = el("div", "ico");
      ico.appendChild(icon(SOURCE_ICON[id]));
      const mid = el("div");
      mid.append(el("div", "n", name), el("div", "d", what));
      const rows = by[id] || [];
      const active = rows.find((r) => r.status === "active");
      const tag = active ? el("span", "tag ok", "Connected")
        : rows.length ? el("span", "tag warn", rows[0].status.replace(/_/g, " ")) : el("span", "tag", "Not connected");
      row.append(ico, mid, tag);
      holder.appendChild(row);
    }

    const soon = $("planned");
    soon.replaceChildren();
    for (const [id, name, what] of PLANNED) {
      const row = el("div", "conn soon");
      const ico = el("div", "ico");
      ico.appendChild(icon(id));
      const mid = el("div");
      mid.append(el("div", "n", name), el("div", "d", what));
      row.append(ico, mid, el("span", "tag brand", "Coming soon"));
      soon.appendChild(row);
    }

    const prefs = $("prefs");
    prefs.replaceChildren();
    const paused = status && (status.paused || []).length;
    for (const [n, d, v] of [
      ["Name in meetings", "What people say to get Cue's attention.", "Cue"],
      ["Voice", "Free neural voice, played into the call.", "Ava"],
      ["When Cue speaks", "Only when addressed by name, or any question in a one-on-one.", "When asked"],
      ["Follow-up window", "After answering, short follow-ups need no name.", "45 seconds"],
      ["Workspace status", "Admins can pause Cue from the operator console.", paused ? "Paused" : "Active"],
    ]) {
      const row = el("div", "pref");
      const left = el("div");
      left.append(el("div", "n", n), el("div", "d", d));
      row.append(left, el("div", "v", v));
      prefs.appendChild(row);
    }

    const tiers = $("tiers");
    tiers.replaceChildren();
    for (const [n, label, mode, tone] of TIERS) {
      const row = el("div", "tier");
      row.append(el("b", null, n), el("span", null, label), el("span", `tag ${tone}`, mode));
      tiers.appendChild(row);
    }
  }

  /* ----------------------------------------------------------------- boot -- */
  function boot() {
    buildRail();
    buildChat();
    buildMemory();
    $("joinForm").addEventListener("submit", joinMeeting);
    let start = "meetings";
    try { start = localStorage.getItem("cue.view") || start; } catch (_) { /* storage is optional */ }
    if (location.hash) start = location.hash.slice(1);
    show(VIEWS.some((v) => v.id === start) ? start : "meetings");
    refreshBadge();
    // Polling pauses in a hidden tab; pick the live meeting back up the moment it is visible.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.view === "meetings" && state.meetingId && state.live
          && state.live.status !== "ended") openMeeting(state.meetingId);
    });
    setInterval(() => { if (document.visibilityState === "visible") refreshBadge(); }, 20000);
  }
  boot();
})();
