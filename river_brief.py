"""
Friday River Brief
Fetches live Canterbury river flows via Claude web search,
generates a weekend paddling brief, and emails it to Jason.
"""

import os
import json
import smtplib
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import anthropic

# ---------------------------------------------------------------------------
# Config — all sensitive values come from environment variables / GitHub Secrets
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS     = os.environ["GMAIL_ADDRESS"]       # jjbutler74@gmail.com
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL          = os.environ.get("TO_EMAIL", GMAIL_ADDRESS)

# ---------------------------------------------------------------------------
# Rivers: Jason's log — NZ runs paddled 2+ times since June 2021
# ---------------------------------------------------------------------------

RIVERS = [
    {
        "name": "Hurunui – Maori Gully",
        "section": "Maori Gully (Grade III)",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/65104",
        "gauge_name": "Mandamus",
        "drive_time": "1h 45m",
        "sweet_spot": "25–80 m³/s",
        "good_min": 25,
        "good_max": 80,
        "low_cutoff": 15,
        "high_cutoff": 100,
        "notes": "25–40 is cruisy III, 40–80 pumping, >100 becomes IV+. Most-paddled NZ run.",
    },
    {
        "name": "Ashley – Ashley Gorge",
        "section": "Ashley Gorge (Grade II–III+)",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/66204",
        "gauge_name": "Ashley Gorge",
        "drive_time": "55m",
        "sweet_spot": "40–90 m³/s",
        "good_min": 40,
        "good_max": 90,
        "low_cutoff": 15,
        "high_cutoff": 150,
        "notes": "Gets interesting above 40. At 84 continuous and fun. Above 120 gets committing.",
    },
    {
        "name": "Rangitata Gorge",
        "section": "Rangitata Gorge (Grade IV)",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/69302",
        "gauge_name": "Klondyke",
        "drive_time": "1h 50m",
        "sweet_spot": "45–80 m³/s",
        "good_min": 45,
        "good_max": 80,
        "low_cutoff": 30,
        "high_cutoff": 120,
        "notes": "Crux is the last gorge drop — stay left. Run at 48 and 63 m³/s. Avoid when spiking.",
    },
    {
        "name": "Buller – Earthquake / Granity",
        "section": "Earthquake & Granity (Grade III–III+)",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/64608",
        "gauge_name": "Te Kuha (upper Buller, directional only)",
        "drive_time": "3h 30m",
        "sweet_spot": "40–80 m³/s",
        "good_min": 40,
        "good_max": 80,
        "low_cutoff": 25,
        "high_cutoff": 150,
        "notes": "Long drive. Granity rapid is the centrepiece — 3 laps is the move. Earthquake has big boof waves.",
    },
    {
        "name": "Waimakariri Gorge",
        "section": "Gorge run (Grade II)",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/66401",
        "gauge_name": "Old Highway Bridge",
        "drive_time": "1h 10m",
        "sweet_spot": "30–120 m³/s",
        "good_min": 30,
        "good_max": 120,
        "low_cutoff": 15,
        "high_cutoff": 200,
        "notes": "Mellow but scenic. Good for guests or a family day. Gets fun at higher flows.",
    },
    {
        "name": "Kawarau – Dogleg",
        "section": "Dogleg (Grade III)",
        "gauge_url": "https://flowrate.co.nz/river/kawarau-river/chards",
        "gauge_name": "Chards Farm (ORC gauge)",
        "drive_time": "4h 30m",
        "sweet_spot": "200–350 m³/s",
        "good_min": 200,
        "good_max": 350,
        "low_cutoff": 100,
        "high_cutoff": 450,
        "notes": "Weekend trip. Last big rapid is the star. Run at 258–279 m³/s. Worth it when conditions align.",
    },
]

# ---------------------------------------------------------------------------
# Claude call: fetch flows + generate brief in one shot using web search
# ---------------------------------------------------------------------------

def get_flows_and_brief():
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = datetime.now().strftime("%A %d %B %Y")

    river_list = "\n".join(
        f"{i+1}. {r['name']} ({r['section']}) — gauge: {r['gauge_url']} "
        f"— sweet spot: {r['sweet_spot']} — drive from Christchurch: {r['drive_time']} "
        f"— context: {r['notes']}"
        for i, r in enumerate(RIVERS)
    )

    prompt = f"""Today is {today}. You are generating a Friday river brief for Jason, an experienced whitewater kayaker based in Christchurch, NZ (Grade IV comfort zone, paddles with Patrick as main partner).

Use web_search to fetch the current flow value from each gauge page below. Extract the "Flow m3/s" value shown on each page.

Rivers to check:
{river_list}

After fetching all flows, respond with ONLY valid JSON — no markdown fences, no explanation, just the raw JSON object:
{{
  "flows": [flow1, flow2, flow3, flow4, flow5, flow6],
  "brief": "your brief here"
}}

For flows: numeric m³/s value, or null if unavailable.

For the brief (max 300 words): direct, opinionated weekend assessment. Structure:
- Weekend verdict: one-line call on what to paddle
- Quick 1-2 sentence take on each river worth discussing (skip obviously unrunnable ones, list them as "Not worth it: X, Y")
- Watch for: anything trending worth monitoring for next weekend

Tone: direct paddling mate who checked the gauges. No fluff. Use m³/s."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )

    # Find last text block (after all tool use rounds)
    text_blocks = [b for b in response.content if b.type == "text"]
    if not text_blocks:
        raise ValueError("No text block in Claude response")

    raw = text_blocks[-1].text.strip()

    # Strip markdown fences if Claude added them anyway
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Extract JSON object
    match = re.search(r'\{[\s\S]*"flows"[\s\S]*"brief"[\s\S]*\}', raw)
    if not match:
        raise ValueError(f"Could not find JSON in response: {raw[:500]}")

    parsed = json.loads(match.group(0))
    return parsed["flows"], parsed["brief"]


# ---------------------------------------------------------------------------
# Build HTML email
# ---------------------------------------------------------------------------

def condition(flow, river):
    if flow is None:
        return ("No data", "#888888", "❓")
    if flow < river["low_cutoff"]:
        return ("Too low", "#ef4444", "🔴")
    if flow > river["high_cutoff"]:
        return ("Dangerous", "#7c3aed", "⚠️")
    if river["good_min"] <= flow <= river["good_max"]:
        return ("Sweet spot ✓", "#16a34a", "🟢")
    if flow < river["good_min"]:
        return ("Low but runnable", "#f59e0b", "🟡")
    return ("High — spicy", "#ea580c", "🟠")


def build_email(flows, brief):
    today = datetime.now().strftime("%A %d %B %Y")

    river_rows = ""
    for i, river in enumerate(RIVERS):
        flow = flows[i] if i < len(flows) else None
        label, color, emoji = condition(flow, river)
        flow_display = f"{flow} m³/s" if flow is not None else "No data"

        river_rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #1e3a5f;">
            <strong style="color:#e2e8f0;font-size:14px;">{river['name']}</strong><br>
            <span style="color:#64748b;font-size:12px;">{river['section']} · {river['drive_time']} · Sweet spot {river['sweet_spot']}</span><br>
            <span style="color:#475569;font-size:11px;">{river['notes']}</span>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #1e3a5f;text-align:right;white-space:nowrap;vertical-align:top;">
            <strong style="color:{color};font-size:16px;">{flow_display}</strong><br>
            <span style="color:{color};font-size:12px;">{emoji} {label}</span><br>
            <a href="{river['gauge_url']}" style="color:#3b82f6;font-size:11px;text-decoration:none;">Live gauge ↗</a>
          </td>
        </tr>"""

    brief_html = brief.replace("\n", "<br>")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0f1923;font-family:'Inter',system-ui,sans-serif;">
  <div style="max-width:620px;margin:0 auto;background:#0f1923;color:#e2e8f0;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1a2e44,#0f1923);padding:24px 28px;border-bottom:1px solid #1e3a5f;">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.15em;color:#60a5fa;text-transform:uppercase;margin-bottom:6px;">
        🚣 Canterbury River Intel
      </div>
      <h1 style="margin:0;font-size:22px;font-weight:800;color:#f0f9ff;">Friday River Brief</h1>
      <div style="font-size:12px;color:#64748b;margin-top:6px;">{today}</div>
    </div>

    <!-- Brief -->
    <div style="margin:20px 28px;background:#132338;border-left:3px solid #3b82f6;border-radius:8px;padding:18px 20px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;color:#60a5fa;text-transform:uppercase;margin-bottom:10px;">
        Weekend Assessment
      </div>
      <div style="font-size:14px;line-height:1.75;color:#cbd5e1;">
        {brief_html}
      </div>
    </div>

    <!-- River table -->
    <div style="margin:0 28px 20px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;color:#475569;text-transform:uppercase;margin-bottom:12px;">
        Flow Data
      </div>
      <table style="width:100%;border-collapse:collapse;background:#132338;border-radius:8px;overflow:hidden;border:1px solid #1e3a5f;">
        {river_rows}
      </table>
    </div>

    <!-- Footer -->
    <div style="margin:0 28px 28px;font-size:11px;color:#334155;border-top:1px solid #1e3a5f;padding-top:14px;">
      Rivers from Jason's kayak log — NZ runs paddled 2+ times since June 2021.
      Buller gauge (Te Kuha) is directional only. Kawarau uses ORC gauge.
      Sweet spot bands calibrated from personal log notes.
    </div>

  </div>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# Send email
# ---------------------------------------------------------------------------

def send_email(html, flows):
    today = datetime.now().strftime("%d %b")

    # Build a quick subject line based on best condition
    best = None
    for i, river in enumerate(RIVERS):
        flow = flows[i] if i < len(flows) else None
        if flow is not None:
            label, _, _ = condition(flow, river)
            if "Sweet spot" in label:
                best = river["name"]
                break

    subject = f"🚣 River Brief {today}"
    if best:
        subject += f" — {best} is on"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)

    print(f"Email sent: {subject}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Fetching flows and generating brief...")
    flows, brief = get_flows_and_brief()
    print(f"Flows: {flows}")
    print(f"Brief: {brief[:200]}...")

    html = build_email(flows, brief)
    send_email(html, flows)
    print("Done.")
