"""
Friday River Brief
Fetches live Canterbury river flows from ECan's ArcGIS API (no JS rendering issues),
then calls Claude to generate a weekend paddling brief, and emails it to Jason.
"""

import os
import json
import smtplib
import re
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import anthropic

# ---------------------------------------------------------------------------
# Config — all sensitive values come from environment variables / GitHub Secrets
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL           = os.environ.get("TO_EMAIL", GMAIL_ADDRESS)

# ---------------------------------------------------------------------------
# ECan ArcGIS live layer — returns Current_flow_m3s directly as JSON
# No JS rendering, no scraping. Updates every 15 min.
# ---------------------------------------------------------------------------

ECAN_API = (
    "https://gis.ecan.govt.nz/arcgis/rest/services/Public/WaterQualityandMonitoring"
    "/FeatureServer/12/query?where=SITENUMBER%3D{site}&outFields="
    "SITENAME,Current_flow_m3s,Current_stage_height_m,Change_last_hour_mm,Peak_flow_7_day"
    "&f=json"
)

# ---------------------------------------------------------------------------
# Rivers: Jason's log — NZ runs paddled 2+ times since June 2021
# gauge_id: ECan site number (None = no ECan gauge, check manually)
# ---------------------------------------------------------------------------

RIVERS = [
    {
        "name": "Hurunui – Maori Gully",
        "section": "Maori Gully (Grade III)",
        "gauge_id": 65104,
        "gauge_label": "Mandamus gauge",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/65104",
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
        "gauge_id": 66204,
        "gauge_label": "Ashley Gorge gauge",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/66204",
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
        "gauge_id": 69302,
        "gauge_label": "Klondyke gauge",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/69302",
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
        "gauge_id": None,   # Te Kuha has no flow reading in ECan live layer
        "gauge_label": "Check flowrate.co.nz",
        "gauge_url": "https://www.flowrate.co.nz",
        "drive_time": "3h 30m",
        "sweet_spot": "40–80 m³/s",
        "good_min": 40,
        "good_max": 80,
        "low_cutoff": 25,
        "high_cutoff": 150,
        "notes": "Long drive. Granity rapid is the centrepiece. Earthquake has big boof waves.",
    },
    {
        "name": "Waimakariri Gorge",
        "section": "Gorge run (Grade II)",
        "gauge_id": 66401,
        "gauge_label": "Old Highway Bridge gauge",
        "gauge_url": "https://www.ecan.govt.nz/data/riverflow/sitedetails/66401",
        "drive_time": "1h 10m",
        "sweet_spot": "30–120 m³/s",
        "good_min": 30,
        "good_max": 120,
        "low_cutoff": 15,
        "high_cutoff": 200,
        "notes": "Mellow but scenic. Good for guests. Gets fun at higher flows.",
    },
    {
        "name": "Kawarau – Dogleg",
        "section": "Dogleg (Grade III)",
        "gauge_id": None,   # ORC gauge only
        "gauge_label": "ORC gauge — check flowrate.co.nz",
        "gauge_url": "https://flowrate.co.nz/river/kawarau-river/chards",
        "drive_time": "4h 30m",
        "sweet_spot": "200–350 m³/s",
        "good_min": 200,
        "good_max": 350,
        "low_cutoff": 100,
        "high_cutoff": 450,
        "notes": "Weekend trip. Last big rapid is the star. Run at 258–279 m³/s.",
    },
]

# ---------------------------------------------------------------------------
# Fetch flows from ECan ArcGIS API
# ---------------------------------------------------------------------------

def fetch_ecan_flow(site_id):
    """Returns dict with flow, stage, change_per_hour, peak_7day — or None on failure."""
    try:
        url = ECAN_API.format(site=site_id)
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.load(r)
        if d.get("features"):
            a = d["features"][0]["attributes"]
            return {
                "flow": a.get("Current_flow_m3s"),
                "stage": a.get("Current_stage_height_m"),
                "change_mm_hr": a.get("Change_last_hour_mm"),
                "peak_7day": a.get("Peak_flow_7_day"),
            }
    except Exception as e:
        print(f"  Fetch failed for site {site_id}: {e}")
    return None

def fetch_all_flows():
    results = []
    for river in RIVERS:
        if river["gauge_id"]:
            print(f"  Fetching {river['name']}...")
            data = fetch_ecan_flow(river["gauge_id"])
            results.append(data)
        else:
            results.append(None)  # No ECan gauge
    return results

# ---------------------------------------------------------------------------
# Generate brief via Claude
# ---------------------------------------------------------------------------

def generate_brief(flow_data):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = datetime.now().strftime("%A %d %B %Y")

    river_summaries = []
    for i, river in enumerate(RIVERS):
        d = flow_data[i]
        if d and d["flow"] is not None:
            trend = "rising" if (d["change_mm_hr"] or 0) > 5 else \
                    "falling" if (d["change_mm_hr"] or 0) < -5 else "stable"
            summary = (
                f"{river['name']} ({river['section']}): {round(d['flow'], 1)} m³/s, {trend} "
                f"({d['change_mm_hr']:+d}mm/hr), 7-day peak {round(d['peak_7day'], 0) if d['peak_7day'] else 'unknown'} m³/s. "
                f"Sweet spot: {river['sweet_spot']}. Drive: {river['drive_time']}. "
                f"Notes: {river['notes']}"
            )
        else:
            summary = (
                f"{river['name']} ({river['section']}): no live data (check {river['gauge_url']}). "
                f"Sweet spot: {river['sweet_spot']}. Drive: {river['drive_time']}."
            )
        river_summaries.append(summary)

    prompt = f"""Today is {today}. Generate a Friday river brief for Jason — experienced whitewater kayaker, Christchurch NZ, Grade IV comfort zone, paddles with Patrick as main partner.

Current flow data:
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(river_summaries))}

Write a direct, opinionated weekend assessment (max 300 words). Structure:
- Weekend verdict: one-line call on what to paddle this weekend
- Quick 1-2 sentence take on each river worth discussing (skip clearly unrunnable ones, note them as "Not worth it: X, Y")
- Watch for: anything trending worth monitoring for next weekend

Tone: direct paddling mate who checked the gauges. No fluff. Use m³/s throughout."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text

# ---------------------------------------------------------------------------
# Condition labelling
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

# ---------------------------------------------------------------------------
# Build HTML email
# ---------------------------------------------------------------------------

def build_email(flow_data, brief):
    today = datetime.now().strftime("%A %d %B %Y")
    fetched_at = datetime.now().strftime("%H:%M NZT")

    river_rows = ""
    for i, river in enumerate(RIVERS):
        d = flow_data[i]
        flow = d["flow"] if d else None
        label, color, emoji = condition(flow, river)
        flow_display = f"{round(flow, 1)} m³/s" if flow is not None else "No data"

        trend_html = ""
        if d and d.get("change_mm_hr") is not None:
            ch = d["change_mm_hr"]
            arrow = "↑" if ch > 5 else "↓" if ch < -5 else "→"
            trend_html = f'<span style="color:#94a3b8;font-size:11px;">{arrow} {ch:+d}mm/hr</span>'

        peak_html = ""
        if d and d.get("peak_7day"):
            peak_html = f'<br><span style="color:#475569;font-size:11px;">7d peak: {round(d["peak_7day"],0):.0f} m³/s</span>'

        river_rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #1e3a5f;vertical-align:top;">
            <strong style="color:#e2e8f0;font-size:14px;">{river['name']}</strong><br>
            <span style="color:#64748b;font-size:12px;">{river['section']} · {river['drive_time']} · {river['sweet_spot']}</span><br>
            <span style="color:#475569;font-size:11px;">{river['notes']}</span>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #1e3a5f;text-align:right;white-space:nowrap;vertical-align:top;">
            <strong style="color:{color};font-size:16px;">{flow_display}</strong><br>
            <span style="color:{color};font-size:12px;">{emoji} {label}</span>
            {peak_html}<br>
            {trend_html}
            <a href="{river['gauge_url']}" style="color:#3b82f6;font-size:11px;text-decoration:none;display:block;margin-top:3px;">Live gauge ↗</a>
          </td>
        </tr>"""

    brief_html = brief.replace("\n", "<br>")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0f1923;font-family:'Inter',system-ui,sans-serif;">
  <div style="max-width:620px;margin:0 auto;background:#0f1923;color:#e2e8f0;">

    <div style="background:linear-gradient(135deg,#1a2e44,#0f1923);padding:24px 28px;border-bottom:1px solid #1e3a5f;">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.15em;color:#60a5fa;text-transform:uppercase;margin-bottom:6px;">
        🚣 Canterbury River Intel
      </div>
      <h1 style="margin:0;font-size:22px;font-weight:800;color:#f0f9ff;">Friday River Brief</h1>
      <div style="font-size:12px;color:#64748b;margin-top:6px;">{today} · Flows fetched {fetched_at}</div>
    </div>

    <div style="margin:20px 28px;background:#132338;border-left:3px solid #3b82f6;border-radius:8px;padding:18px 20px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;color:#60a5fa;text-transform:uppercase;margin-bottom:10px;">
        Weekend Assessment
      </div>
      <div style="font-size:14px;line-height:1.75;color:#cbd5e1;">{brief_html}</div>
    </div>

    <div style="margin:0 28px 20px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;color:#475569;text-transform:uppercase;margin-bottom:12px;">
        Flow Data
      </div>
      <table style="width:100%;border-collapse:collapse;background:#132338;border-radius:8px;overflow:hidden;border:1px solid #1e3a5f;">
        {river_rows}
      </table>
    </div>

    <div style="margin:0 28px 28px;font-size:11px;color:#334155;border-top:1px solid #1e3a5f;padding-top:14px;">
      Flows from ECan ArcGIS live API · Updates every 15 min · Rivers from Jason's kayak log (2+ NZ sessions since June 2021) ·
      Buller and Kawarau have no ECan gauge — check flowrate.co.nz manually.
    </div>

  </div>
</body>
</html>"""

    return html

# ---------------------------------------------------------------------------
# Send email
# ---------------------------------------------------------------------------

def send_email(html, flow_data):
    today = datetime.now().strftime("%d %b")

    best = next(
        (RIVERS[i]["name"] for i, d in enumerate(flow_data)
         if d and d["flow"] is not None
         and RIVERS[i]["good_min"] <= d["flow"] <= RIVERS[i]["good_max"]),
        None
    )

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
    print("Fetching flows from ECan ArcGIS API...")
    flow_data = fetch_all_flows()

    for i, river in enumerate(RIVERS):
        d = flow_data[i]
        if d:
            print(f"  {river['name']}: {d['flow']} m³/s")
        else:
            print(f"  {river['name']}: no data")

    print("Generating brief via Claude...")
    brief = generate_brief(flow_data)
    print(f"Brief: {brief[:150]}...")

    html = build_email(flow_data, brief)
    send_email(html, flow_data)
    print("Done.")
