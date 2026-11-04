"""Fallback merge approval page, independent of the built Svelte UI."""

# Inline CSS and JavaScript are kept with the standalone page.
# ruff: noqa: E501

from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route


def merge_ready_plans(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    plans = status.get("plans", [])
    candidates = [
        plan
        for plan in plans
        if isinstance(plan, dict)
        and str(plan.get("status", "")).lower()
        not in {
            "done",
            "cancelled",
            "complete",
            "completed",
            "concluded",
            "abandoned",
            "finished",
        }
        and not plan.get("merge_approved_at")
        and plan.get("merge_state") not in {"approved_not_merged", "merged"}
    ]
    return sorted(candidates, key=lambda plan: not bool(plan.get("awaiting_user")))


def render_approve_page(plans: list[dict[str, Any]]) -> str:
    rows = []
    for plan in plans:
        plan_id = str(plan.get("id", ""))
        title = str(plan.get("title") or plan.get("label") or plan_id)
        action = html.escape(
            "/api/plans/" + quote(plan_id, safe="") + "/merge-approval",
            quote=True,
        )
        description = (
            "Ready for your approval"
            if plan.get("awaiting_user")
            else "Awaiting a merge decision"
        )
        rows.append(
            '<article class="plan"><h2>'
            + html.escape(title)
            + "</h2><p>"
            + html.escape(description)
            + '</p><form data-action="'
            + action
            + '"><label>Optional note'
            '<textarea name="note" maxlength="500" rows="3"></textarea></label>'
            '<button type="submit">Approve merge</button><output aria-live="polite"></output></form></article>'
        )
    content = "".join(rows) or '<p class="empty">No plans need merge approval.</p>'
    return (
        """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Approve merges</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:24px 16px;font:17px/1.45 system-ui,sans-serif;background:#f5f7fb;color:#172033}
main{max-width:720px;margin:0 auto}h1{font-size:1.65rem}.plan{margin:16px 0;padding:18px;border:1px solid #d9dfeb;border-radius:16px;background:#fff;overflow-wrap:anywhere}
h2{font-size:1.2rem;margin:0}p{color:#5b6475}label{display:block}textarea{display:block;width:100%;max-width:100%;margin:6px 0 12px;padding:10px;border:1px solid #aab4c5;border-radius:10px;font:inherit;resize:vertical}
button{min-height:48px;padding:0 18px;border:0;border-radius:12px;background:#2459d3;color:white;font:600 1rem system-ui;cursor:pointer}output{display:block;margin-top:10px}.empty{padding:18px}
@media(prefers-color-scheme:dark){body{background:#10141d;color:#edf1f8}.plan{background:#1a2230;border-color:#344054}p{color:#bdc6d5}textarea{background:#111722;color:#edf1f8;border-color:#59677c}.empty{color:#bdc6d5}}
</style><main><h1>Approve merges</h1>"""
        + content
        + """</main>
<script>for(const form of document.querySelectorAll('form[data-action]'))form.addEventListener('submit',async event=>{event.preventDefault();const button=form.querySelector('button');const output=form.querySelector('output');button.disabled=true;try{const pairingResponse=await fetch('/api/pairing',{cache:'no-store'});const pairing=pairingResponse.ok?await pairingResponse.json():{paired:true,csrf:null};if(!pairing.paired)throw new Error('Pair this browser with the runner first');const headers={'content-type':'application/json'};if(pairing.csrf)headers['x-varde-csrf']=pairing.csrf;const response=await fetch(form.dataset.action,{method:'POST',headers,body:JSON.stringify({note:form.elements.note.value||null})});if(!response.ok)throw new Error('Approval failed ('+response.status+')');form.closest('.plan').innerHTML='<p role="status">Merge approved</p>'}catch(error){output.textContent=error.message;button.disabled=false}})</script></html>"""
    )


def create_approve_page_routes(
    read_status: Callable[[], Mapping[str, Any]],
) -> list[Route]:
    async def approve_page(_: Request) -> HTMLResponse:
        return HTMLResponse(render_approve_page(merge_ready_plans(read_status())))

    return [Route("/approve", approve_page, methods=["GET"])]
