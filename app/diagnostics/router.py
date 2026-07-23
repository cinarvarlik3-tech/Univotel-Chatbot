"""
Live-test diagnostic UI: HTML dashboard + SSE stream + JSON APIs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from app.diagnostics.trace import get_trace_hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def diagnostics_home() -> str:
    """Primary live trace dashboard (auto-connects SSE)."""
    return _DASHBOARD_HTML


@router.get("/flow", response_class=HTMLResponse)
async def diagnostics_flow() -> str:
    """Pipeline-oriented view: layer counts and recent path per conversation."""
    return _FLOW_HTML


@router.get("/api/stats")
async def api_stats():
    hub = get_trace_hub()
    if not hub.enabled:
        return JSONResponse({"enabled": False, "message": "Set LIVE_TRACE_ENABLED=true and restart"})
    return JSONResponse(await hub.stats())


@router.get("/api/events")
async def api_events(
    limit: int = Query(500, ge=1, le=5000),
    chatwoot_conversation_id: Optional[int] = None,
    layer: Optional[str] = None,
):
    hub = get_trace_hub()
    if not hub.enabled:
        return JSONResponse({"enabled": False, "events": []})
    events = await hub.recent(
        limit,
        chatwoot_conversation_id=chatwoot_conversation_id,
        layer=layer,
    )
    return JSONResponse({"enabled": True, "events": events})


@router.get("/api/stream")
async def api_stream(request: Request):
    """Server-Sent Events: one JSON object per trace line."""
    hub = get_trace_hub()
    if not hub.enabled:
        async def _disabled():
            yield "event: error\ndata: {\"message\":\"trace disabled\"}\n\n"
        return StreamingResponse(_disabled(), media_type="text/event-stream")

    async def _gen():
        # Replay recent tail so the UI is not empty on connect
        for row in await hub.recent(200):
            if await request.is_disconnected():
                return
            yield f"data: {json.dumps(row, ensure_ascii=False, default=str)}\n\n"
        async for ev in hub.subscribe():
            if await request.is_disconnected():
                break
            yield f"data: {ev.to_json()}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Univotel Live Trace</title>
  <style>
    :root {
      --bg: #0f1419; --panel: #1a2332; --border: #2d3a4f;
      --text: #e7ecf3; --muted: #8b9cb3;
      --http: #6eb5ff; --webhook: #a78bfa; --debounce: #fbbf24;
      --info: #34d399; --rec: #f472b6; --chatwoot: #38bdf8;
      --warn: #fb923c; --err: #f87171;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
      background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; }
    header { padding: 10px 14px; border-bottom: 1px solid var(--border); display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    header h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: 0.02em; }
    header a { color: var(--http); text-decoration: none; }
    .pill { padding: 2px 8px; border-radius: 999px; background: var(--panel); border: 1px solid var(--border); color: var(--muted); }
    .pill.ok { color: #34d399; border-color: #065f46; }
    .pill.bad { color: #f87171; border-color: #7f1d1d; }
    main { flex: 1; display: grid; grid-template-columns: 280px 1fr 340px; min-height: 0; }
    aside, section { border-right: 1px solid var(--border); overflow: auto; padding: 10px; }
    section:last-child { border-right: none; }
    label { display: block; color: var(--muted); font-size: 11px; margin-bottom: 4px; }
    input, select, button {
      width: 100%; margin-bottom: 8px; padding: 6px 8px; border-radius: 6px;
      border: 1px solid var(--border); background: var(--panel); color: var(--text);
    }
    button { cursor: pointer; }
    button:hover { border-color: var(--http); }
    #events { list-style: none; margin: 0; padding: 0; }
    #events li {
      padding: 6px 8px; border-bottom: 1px solid var(--border); cursor: pointer;
      display: grid; grid-template-columns: 52px 72px 1fr; gap: 8px; align-items: start;
    }
    #events li:hover { background: rgba(255,255,255,0.04); }
    #events li.sel { background: rgba(110,181,255,0.12); }
    .layer { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
    .layer.http { color: var(--http); }
    .layer.webhook { color: var(--webhook); }
    .layer.debounce { color: var(--debounce); }
    .layer.infoGatherer { color: var(--info); }
    .layer.recEngine { color: var(--rec); }
    .layer.chatwoot { color: var(--chatwoot); }
    .layer.internal { color: var(--warn); }
    .ev { color: var(--muted); }
    .ts { color: var(--muted); font-size: 11px; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 11px; }
    .stats { font-size: 11px; color: var(--muted); line-height: 1.6; }
  </style>
</head>
<body>
  <header>
    <h1>Univotel Live Trace</h1>
    <span id="conn" class="pill bad">SSE disconnected</span>
    <span id="seq" class="pill">seq 0</span>
    <a href="/diagnostics/flow">Pipeline view →</a>
    <a href="/diagnostics/api/events?limit=2000" target="_blank">Export JSON</a>
  </header>
  <main>
    <aside>
      <label>Filter Chatwoot conv ID</label>
      <input id="fCwid" type="number" placeholder="e.g. 1695"/>
      <label>Filter layer</label>
      <select id="fLayer">
        <option value="">(all)</option>
        <option>http</option>
        <option>webhook</option>
        <option>debounce</option>
        <option>infoGatherer</option>
        <option>recEngine</option>
        <option>internal</option>
        <option>chatwoot</option>
      </select>
      <label><input type="checkbox" id="autoScroll" checked/> Auto-scroll</label>
      <label><input type="checkbox" id="pause"/> Pause incoming</label>
      <button id="btnClear">Clear view (UI only)</button>
      <div class="stats" id="layerStats"></div>
    </aside>
    <section>
      <ul id="events"></ul>
    </section>
    <section>
      <label>Event detail</label>
      <pre id="detail">Select an event</pre>
    </section>
  </main>
  <script>
    const eventsEl = document.getElementById('events');
    const detailEl = document.getElementById('detail');
    const connEl = document.getElementById('conn');
    const seqEl = document.getElementById('seq');
    const layerStatsEl = document.getElementById('layerStats');
    const maxRows = 1500;
    let rows = [];
    let selectedSeq = null;
    const layerCounts = {};

    function passFilter(ev) {
      const cwid = document.getElementById('fCwid').value;
      const layer = document.getElementById('fLayer').value;
      if (cwid && String(ev.chatwoot_conversation_id || '') !== cwid) return false;
      if (layer && ev.layer !== layer) return false;
      return true;
    }

    function render() {
      eventsEl.innerHTML = '';
      const filtered = rows.filter(passFilter).slice(-maxRows);
      for (const ev of filtered) {
        const li = document.createElement('li');
        if (ev.seq === selectedSeq) li.classList.add('sel');
        li.dataset.seq = ev.seq;
        li.innerHTML = `
          <span class="ts">${(ev.ts || '').slice(11, 19)}</span>
          <span class="layer ${ev.layer}">${ev.layer}</span>
          <span><span class="ev">${ev.event}</span>
            ${ev.chatwoot_conversation_id ? ' · cw=' + ev.chatwoot_conversation_id : ''}</span>`;
        li.onclick = () => { selectedSeq = ev.seq; detailEl.textContent = JSON.stringify(ev, null, 2); render(); };
        eventsEl.appendChild(li);
      }
      layerStatsEl.textContent = Object.entries(layerCounts).sort((a,b)=>b[1]-a[1]).map(([k,v])=>k+': '+v).join('\\n') || 'No events yet';
      if (document.getElementById('autoScroll').checked) {
        eventsEl.parentElement.scrollTop = eventsEl.parentElement.scrollHeight;
      }
    }

    function push(ev) {
      if (document.getElementById('pause').checked) return;
      rows.push(ev);
      if (rows.length > maxRows * 2) rows = rows.slice(-maxRows);
      layerCounts[ev.layer] = (layerCounts[ev.layer] || 0) + 1;
      seqEl.textContent = 'seq ' + ev.seq;
      render();
    }

    document.getElementById('fCwid').oninput = render;
    document.getElementById('fLayer').onchange = render;
    document.getElementById('btnClear').onclick = () => { rows = []; selectedSeq = null; render(); };

    const es = new EventSource('/diagnostics/api/stream');
    es.onopen = () => { connEl.textContent = 'SSE connected'; connEl.className = 'pill ok'; };
    es.onerror = () => { connEl.textContent = 'SSE disconnected'; connEl.className = 'pill bad'; };
    es.onmessage = (m) => {
      try { push(JSON.parse(m.data)); } catch (e) {}
    };

    fetch('/diagnostics/api/stats').then(r=>r.json()).then(s => {
      if (!s.enabled) {
        connEl.textContent = 'Trace disabled — set LIVE_TRACE_ENABLED=true';
        connEl.className = 'pill bad';
      }
    });
  </script>
</body>
</html>
"""


_FLOW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Univotel Pipeline Trace</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f1419; color: #e7ecf3; margin: 16px; }
    a { color: #6eb5ff; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border: 1px solid #2d3a4f; padding: 8px; text-align: left; }
    th { background: #1a2332; }
    .path { font-family: ui-monospace, monospace; font-size: 12px; color: #8b9cb3; }
  </style>
</head>
<body>
  <h1>Pipeline trace by conversation</h1>
  <p><a href="/diagnostics">← Live stream</a> · refreshes every 3s</p>
  <table>
    <thead><tr><th>CW ID</th><th>Events</th><th>Last layer</th><th>Recent path (newest last)</th></tr></thead>
    <tbody id="tb"></tbody>
  </table>
  <script>
    async function refresh() {
      const r = await fetch('/diagnostics/api/events?limit=3000');
      const j = await r.json();
      const by = {};
      for (const e of j.events || []) {
        const id = e.chatwoot_conversation_id || '—';
        if (!by[id]) by[id] = [];
        by[id].push(e);
      }
      const tb = document.getElementById('tb');
      tb.innerHTML = '';
      for (const [id, evs] of Object.entries(by).sort((a,b)=>b[1].length-a[1].length)) {
        const path = evs.slice(-12).map(x => x.layer + ':' + x.event).join(' → ');
        const last = evs[evs.length-1];
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${id}</td><td>${evs.length}</td><td>${last.layer}</td><td class="path">${path}</td>`;
        tb.appendChild(tr);
      }
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""
