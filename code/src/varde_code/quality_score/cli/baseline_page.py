"""The self-contained baseline page: inline script and style, CSP by hash."""
# ruff: noqa: E501 (inline JavaScript)

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

STYLE = """
body{font:14px system-ui,sans-serif;margin:1.5rem;max-width:60rem}
select,button{margin-right:.5rem}
textarea{width:100%;height:22rem;font:13px ui-monospace,monospace}
#score{font-size:2rem;margin:.5rem 0}
#notice,#status{color:#a40}
pre#debug{background:#eee;padding:.5rem;overflow:auto}
"""

SCRIPT = """
const token = document.body.dataset.token;
const $ = (id) => document.getElementById(id);
let problems = {};
async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Varde-Token": token},
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  return {status: response.status, data};
}
const ADVISORIES = ["monolith", "delegation", "fragmentation"];
function show(data) {
  $("score").textContent = data.score === null || data.score === undefined
    ? "no score" : data.score.toFixed(1) + " / 100";
  $("notice").textContent = data.notice || (data.tests_passed === false
    ? "Behaviour tests fail for this code." : data.tests_passed === null
    ? "Tests were not run (toolchain missing)." : "");
  $("label").textContent = data.score === null || data.score === undefined ? ""
    : "Calibration: " + String(data.calibration || "").replace("not validated", "not validated / report-only");
  $("advisories").replaceChildren();
  for (const key of ADVISORIES) {
    if (!data[key]) continue;
    const note = document.createElement("li");
    note.textContent = "Advisory (score unchanged): " + data[key].action;
    $("advisories").appendChild(note);
  }
  const list = $("categories");
  list.replaceChildren();
  for (const c of data.categories || []) {
    const item = document.createElement("li");
    item.textContent = c.name + ": -" + c.points_lost.toFixed(1) + " (" + c.hint + ")";
    list.appendChild(item);
  }
  if ($("debug")) $("debug").textContent = JSON.stringify(data.debug || {}, null, 1);
}
async function load() {
  const key = {problem: $("problem").value, language: $("language").value};
  const query = "?problem=" + encodeURIComponent(key.problem) + "&language=" + key.language;
  const {data} = await api("/api/baseline" + query);
  $("statement").textContent = problems[key.problem] || "";
  $("code").value = data.code || "";
  show(data);
}
async function rescore() {
  const body = {problem: $("problem").value, language: $("language").value, code: $("code").value};
  const {status, data} = await api("/api/score", body);
  $("status").textContent = status === 200 ? "" : "Rejected (" + status + ").";
  if (status === 200) show(data);
}
async function save() {
  const body = {problem: $("problem").value, language: $("language").value, code: $("code").value};
  const {status, data} = await api("/api/save", body);
  $("status").textContent = status === 200 ? "Saved: " + data.saved
    : status === 422 ? "Not saved: behaviour tests fail."
    : status === 424 ? "Not saved: the test toolchain is missing." : "Rejected (" + status + ").";
  if (status === 200) show(data);
}
async function reset() {
  const {status} = await api("/api/reset", {language: $("language").value});
  $("status").textContent = status === 200 ? "Custom baseline removed." : "Rejected (" + status + ").";
  load();
}
let timer = null;
$("code").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(rescore, 600); });
$("rescore").addEventListener("click", rescore);
$("save").addEventListener("click", save);
$("reset").addEventListener("click", reset);
$("problem").addEventListener("change", load);
$("language").addEventListener("change", load);
(async () => {
  const {data} = await api("/api/problems");
  problems = data.statements;
  for (const id of data.problems) $("problem").add(new Option(id, id));
  for (const id of data.languages) $("language").add(new Option(id, id));
  load();
})();
"""

BODY = """<h1>Quality baseline</h1>
<p><select id="problem"></select><select id="language"></select></p>
<p id="statement"></p>
<textarea id="code" spellcheck="false"></textarea>
<p><button id="rescore">Re-score</button><button id="save">Save as my baseline</button>
<button id="reset">Reset my baseline</button></p>
<div id="score"></div><div id="label"></div><div id="notice"></div><div id="status"></div>
<ul id="categories"></ul>
<ul id="advisories"></ul>
{debug}"""


@dataclass(frozen=True)
class Page:
    html: str
    csp: str


def _hash(text: str) -> str:
    digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
    return f"'sha256-{digest}'"


def build_page(token: str, debug: bool) -> Page:
    """Page HTML plus the CSP that allows exactly its inline script and style."""
    extra = '<h2>Debug</h2><pre id="debug"></pre>' if debug else ""
    body = BODY.format(debug=extra)
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>Quality baseline</title><style>{STYLE}</style></head>"
        f'<body data-token="{token}">{body}<script>{SCRIPT}</script></body></html>'
    )
    csp = (
        f"default-src 'none'; script-src {_hash(SCRIPT)}; style-src {_hash(STYLE)}; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return Page(html, csp)
