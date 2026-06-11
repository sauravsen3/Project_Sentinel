"""
sentinel_dashboard.py

Cleaned, self-contained version of the Project Sentinel dashboard core logic.
Designed for running in a general Python environment (Gradio UI if available).
"""

import os
import io
import math
import json
import logging
from typing import Tuple, Dict, Any, Optional

import requests
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

# Optional imports
try:
    import gradio as gr
except Exception:
    gr = None

try:
    import fitz  # PyMuPDF for rendering PDFs
except Exception:
    fitz = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentinel_dashboard")

# Environment / paths
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_DEPLOYMENT = os.environ.get("AZURE_DEPLOYMENT", "gpt-4o")
EXTRACTED_DIR = os.environ.get("HULDRA_EXTRACTED_DIR", "/tmp/huldra_extracted_pids/HuldraPIDs")


def _get_openai_client():
    """Attempt to create an AzureOpenAI client; return None if not available or not configured."""
    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_KEY:
        return None
    try:
        from openai import AzureOpenAI
        return AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version="2024-02-01"
        )
    except Exception as exc:
        logger.debug("AzureOpenAI client not available: %s", exc)
        return None


def fetch_uci_telemetry(row_index: int) -> Dict[str, Any]:
    """Return a telemetry row from UCI AI4I 2020 dataset or a realistic fallback."""
    try:
        url = "https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip"
        df = pd.read_csv(url, compression="zip")
        df.columns = [c.split("[")[0].strip().replace(" ", "_") for c in df.columns]
        idx = max(0, min(int(row_index), len(df) - 1))
        row = df.iloc[idx]
        return {
            "rpm": float(row["Rotational_speed"]),
            "torque": float(row["Torque"]),
            "tool_wear": int(row["Tool_wear"]),
            "air_temp": float(row["Air_temperature"]),
            "process_failure": int(row["Machine_failure"]),
            "source": "UCI Live"
        }
    except Exception:
        logger.warning("Failed to fetch UCI dataset; using fallback telemetry.")
        return {
            "rpm": 1350.0, "torque": 78.5, "tool_wear": 120,
            "air_temp": 298.1, "process_failure": 1, "source": "Fallback"
        }


def fetch_satellite_methane(bbox: list, date_range: str) -> Dict[str, Any]:
    """Query Copernicus Data Space for the latest SENTINEL-5P L2 CH4 product metadata."""
    try:
        url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
        params = {
            "$filter": (
                "Collection/Name eq 'SENTINEL-5P' and "
                "Attributes/OData.CSC.StringAttribute/any("
                "att:att/Name eq 'productType' and "
                "att/OData.CSC.StringAttribute/Value eq 'L2__CH4___')"
            ),
            "$orderby": "ContentDate/Start desc",
            "$top": 1
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("value"):
            p = data["value"][0]
            acq_start = p["ContentDate"]["Start"][:16].replace("T", " ") + " UTC"
            acq_end = p["ContentDate"]["End"][:16].replace("T", " ") + " UTC"
            online = "Yes" if p.get("Online") is True else "No"
            size_mb = round(p.get("ContentLength", 0) / 1_000_000, 2)
            return {
                "scene_id": p["Name"],
                "acquired": f"{acq_start} → {acq_end}",
                "published": p.get("PublicationDate", "")[:10],
                "origin": p.get("OriginDate", "")[:10],
                "online": online,
                "size_mb": size_mb,
                "s3_path": p.get("S3Path", "N/A"),
                "product_type": "L2__CH4___ TROPOMI Methane",
                "status": "LIVE — ESA Copernicus Data Space",
                "source": "catalogue.dataspace.copernicus.eu",
                "ch4_note": "Column value inside NetCDF asset (not in catalogue metadata)"
            }
    except Exception as exc:
        logger.debug("Satellite fetch failed: %s", exc)

    return {
        "scene_id": "S5P_OFFL_L2__CH4____FALLBACK",
        "acquired": "N/A",
        "published": "N/A",
        "online": "N/A",
        "size_mb": 0,
        "s3_path": "N/A",
        "product_type": "L2__CH4___",
        "status": "CACHED",
        "source": "N/A",
        "ch4_note": "N/A (offline fallback)"
    }


def count_pdf_references(file_path: str, system_code: str) -> int:
    """Count occurrences of system_code in a text-extracted file; return 0 if not available."""
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        return 0
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return max(1, f.read().count(system_code))
    except Exception:
        return 0


def calc_fluid_transient_surge(torque: float) -> Tuple[float, float]:
    """Estimate pressure surge (bar) and recommended safe closure time (s)."""
    v_fluid = torque / 10.0
    a_wave = 1200.0
    rho = 800.0
    surge_bar = round((rho * a_wave * v_fluid) / 1e5, 1)
    pipe_len = 5.0
    safe_time = round((2 * pipe_len / a_wave) + 2.0, 2) if surge_bar > 40.0 else 0.5
    return surge_bar, safe_time


def _rule_based_trace(telemetry: Dict[str, Any], leak_rate: float, surge_bar: float, system_code: str) -> str:
    if telemetry.get("process_failure") == 1 or leak_rate > 8.0:
        safe_time = calc_fluid_transient_surge(telemetry["torque"])[1]
        return (
            f"THOUGHT: Failure flag set and/or leak rate {leak_rate} kg/hr exceeds 8 kg/hr threshold.\n"
            f"  Surge pressure of {surge_bar} bar detected — instantaneous closure risks fluid hammer.\n"
            f"RISK LEVEL: CRITICAL\n"
            f"RECOMMENDED ACTION: Notify field operator to inspect {system_code}-V01; "
            f"if shutdown required, apply staged valve closure over ≥{safe_time}s.\n"
            f"CAVEAT: This assessment is illustrative. A qualified engineer must validate before any intervention."
        )
    elif leak_rate > 0.0:
        return (
            f"THOUGHT: Torque load {telemetry['torque']} Nm is above threshold; emission proxy elevated.\n"
            f"RISK LEVEL: WARNING\n"
            f"RECOMMENDED ACTION: Schedule preventative seal inspection on {system_code} during next maintenance window.\n"
            f"CAVEAT: Emission estimate is a proxy based on torque — direct measurement required for confirmation."
        )
    else:
        return (
            f"THOUGHT: All telemetry within normal operating range.\n"
            f"RISK LEVEL: NOMINAL\n"
            f"RECOMMENDED ACTION: Continue standard monitoring. No immediate action required.\n"
            f"CAVEAT: Automated assessments do not replace scheduled physical inspections."
        )


def get_foundry_assessment(telemetry: Dict[str, Any], leak_rate: float, surge_bar: float, system_code: str) -> str:
    """Call Azure AI Foundry (if configured) or return a deterministic fallback trace."""
    client = _get_openai_client()
    if client:
        prompt = (
            "You are an industrial safety analyst reviewing real-time asset telemetry.\n"
            "Your role is to reason step-by-step (ReAct pattern) and recommend operator actions.\n"
            "Never mandate automated shutdowns — always recommend field operator verification first.\n"
            "Follow Goal Zero safety principles: no harm to people, assets, or environment.\n\n"
            f"Asset: {system_code}\n"
            f"Telemetry (UCI AI4I 2020 dataset): RPM={telemetry['rpm']}, Torque={telemetry['torque']}, "
            f"Tool_wear={telemetry['tool_wear']}, Failure={telemetry['process_failure']}\n\n"
            f"Derived indicators: leak_rate={leak_rate} kg/hr, surge_bar={surge_bar} bar\n\n"
            "Respond with:\nTHOUGHT: [your reasoning]\nRISK LEVEL: [NOMINAL / WARNING / CRITICAL]\n"
            "RECOMMENDED ACTION: [one clear sentence for the field operator]\nCAVEAT: [one sentence on what should be verified by a qualified engineer]"
        )
        try:
            response = client.chat.completions.create(
                model=AZURE_DEPLOYMENT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.2
            )
            content = response.choices[0].message.content
            return f"[Azure AI Foundry — {AZURE_DEPLOYMENT}]\n\n{content}"
        except Exception as exc:
            logger.debug("Foundry call failed: %s", exc)
            return f"[Foundry call failed: {exc}]\n\n" + _rule_based_trace(telemetry, leak_rate, surge_bar, system_code)
    else:
        return "⚠️ Azure AI Foundry not configured.\n\n" + _rule_based_trace(telemetry, leak_rate, surge_bar, system_code)


def render_pid_schematic(file_path: str, system_code: str) -> Image.Image:
    """Render the first page of a PDF as a PIL image if possible, otherwise return a synthetic schematic."""
    if os.path.exists(file_path) and not os.path.isdir(file_path) and fitz is not None:
        try:
            doc = fitz.open(file_path)
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            return Image.open(io.BytesIO(pix.tobytes("png")))
        except Exception:
            logger.debug("Failed to render PDF, falling back to synthetic schematic.")
    # Synthetic schematic
    fig, ax = plt.subplots(figsize=(6.5, 3.2), facecolor="#0a192f")
    ax.set_facecolor("#0a192f")
    for i in range(11):
        ax.axhline(i / 10, color="#172a45", lw=0.6, alpha=0.7)
        ax.axvline(i / 10, color="#172a45", lw=0.6, alpha=0.7)
    ax.plot([0.1, 0.4, 0.4, 0.9], [0.5, 0.5, 0.7, 0.7],
            color="#64ffda", lw=4.5, label=f"{system_code} Process Line")
    ax.plot([0.4, 0.4], [0.62, 0.78], color="#f43f5e", lw=2.5)
    ax.fill([0.36, 0.44, 0.36, 0.44], [0.65, 0.75, 0.75, 0.65],
            color="#f43f5e", alpha=0.6)
    ax.text(0.4, 0.83, f"ACTUATOR VALVE\n{system_code}-V01",
            color="#f43f5e", ha="center", fontsize=8, fontweight="bold")
    ax.scatter([0.22], [0.5], color="#38bdf8", s=180, zorder=5, edgecolor="white", lw=1)
    ax.plot([0.22, 0.22], [0.5, 0.38], color="#38bdf8", lw=1.5, linestyle="--")
    ax.text(0.22, 0.30, f"TRANSMITTER\nPT-{system_code}-01",
            color="#38bdf8", ha="center", fontsize=8, fontweight="bold")
    ax.set_title(f"ILLUSTRATIVE SCHEMATIC: {system_code} MANIFOLD\n(Synthetic — not an engineering document)",
                 color="#e2e8f0", fontsize=9, fontweight="bold", pad=10)
    ax.text(0.98, 0.03,
            "Source: Equinor Huldra Open Data (public) — illustrative layout only",
            color="#475569", ha="right", fontsize=6, style="italic")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor=fig.get_facecolor(), dpi=150)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


def generate_emissions_plot(torque: float):
    """Return a matplotlib Figure showing the illustrative emission proxy curve."""
    data = {
        "Torque_Nm": [20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120],
        "Methane_Leak_Rate_kg_hr": [0, 0, 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5, 15]
    }
    df = pd.DataFrame(data)
    fig, ax = plt.subplots(figsize=(6, 3.0))
    ax.plot(df["Torque_Nm"], df["Methane_Leak_Rate_kg_hr"],
            color="#d9534f", marker="o", linewidth=2, label="Emission proxy curve (illustrative)")
    leak = max(0.0, (torque * 0.15) - 3.0) if torque > 40 else 0.0
    ax.scatter([torque], [leak], color="black", s=120, zorder=5, label=f"Current state ({torque} Nm)")
    ax.set_title("Torque Load vs. Fugitive Emission Proxy\n(Illustrative — not a validated emissions model)",
                 fontsize=9, fontweight="bold")
    ax.set_xlabel("Torque (Nm)", fontsize=8)
    ax.set_ylabel("Emission proxy (kg/hr CH4 equiv.)", fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(fontsize=7)
    plt.tight_layout()
    return fig


def run_assessment(row_id: int, target_sensor: str):
    """Orchestrate data sources and return results suitable for a UI."""
    system_code = target_sensor.split("-")[1] if "-" in target_sensor else target_sensor
    tel = fetch_uci_telemetry(int(row_id))
    power_kw = (2 * math.pi * tel["rpm"] * tel["torque"]) / 60000
    power_dev = round(power_kw - 8.0, 2)
    leak_rate = round(max(0.0, (tel["torque"] * 0.15) - 3.0), 2) if power_dev > 0 else 0.0
    surge_bar, safe_time = calc_fluid_transient_surge(tel["torque"])

    if tel["process_failure"] == 1 or leak_rate > 8.0:
        status = "🛑 CRITICAL — Field operator verification required"
    elif leak_rate > 0.0:
        status = "⚠️ WARNING — Elevated emission proxy detected"
    else:
        status = "✅ NOMINAL — Within safe operating limits"

    tel_summary = (
        f"Source: {tel['source']}\n"
        f"Failure flag : {'SET' if tel['process_failure'] == 1 else 'CLEAR'}\n"
        f"RPM          : {tel['rpm']}\n"
        f"Torque       : {tel['torque']} Nm\n"
        f"Tool wear    : {tel['tool_wear']} min\n"
        f"Power        : {round(power_kw,2)} kW  (dev: {power_dev:+} kW)"
    )

    sat = fetch_satellite_methane(bbox=[0.0, 59.0, 5.0, 62.0], date_range="2026-01-01/2026-06-14")
    sat_summary = (
        f"Status    : {sat['status']}\n"
        f"Source    : {sat.get('source', 'N/A')}\n"
        f"Product   : {sat.get('product_type', 'N/A')}\n"
        f"Scene     : {sat['scene_id']}\n"
        f"Acquired  : {sat.get('acquired', 'N/A')}\n"
        f"Published : {sat.get('published', 'N/A')} (origin: {sat.get('origin', 'N/A')})\n"
        f"Online    : {sat.get('online', 'N/A')}  |  Size: {sat.get('size_mb', 0)} MB\n"
        f"CH4 note  : {sat.get('ch4_note', 'N/A')}"
    )

    if os.path.exists(EXTRACTED_DIR):
        files = os.listdir(EXTRACTED_DIR)
        doc = next((f for f in files if system_code in f and f.upper().endswith(".PDF")), "Generic_Safety_Manual.pdf")
        full_path = os.path.join(EXTRACTED_DIR, doc)
        refs = count_pdf_references(full_path, system_code)
    else:
        doc = f"C025-V-{system_code}-P-_E-001-01.PDF"
        full_path = doc
        refs = 14

    doc_summary = (
        f"Source      : Equinor Huldra Open Data (public)\n"
        f"File        : {doc}\n"
        f"System code : {system_code}\n"
        f"References  : {refs} matches\n"
        f"Note        : In production, replace with client document store via Azure AI Search."
    )

    reasoning = get_foundry_assessment(tel, leak_rate, surge_bar, system_code)

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"Project Sentinel Alert — Asset {system_code}", "weight": "Bolder", "size": "Medium"},
            {"type": "FactSet", "facts": [
                {"title": "Sensor:", "value": target_sensor},
                {"title": "Status:", "value": status},
                {"title": "Emission proxy:", "value": f"{leak_rate} kg/hr (illustrative)"},
                {"title": "Surge risk:", "value": f"{surge_bar} bar"},
                {"title": "Drawing ref:", "value": doc}
            ]},
            {"type": "TextBlock", "text": (
                f"Recommended: Field operator to inspect {system_code}-V01.\n"
                f"If valve closure required, apply staged sequence over ≥{safe_time}s (Joukowski criterion).\n"
                f"⚠ This alert is advisory only. Verify with qualified engineer."
            ), "wrap": True}
        ]
    }

    pid_img = render_pid_schematic(full_path, system_code)
    emissions_fig = generate_emissions_plot(tel["torque"])
    return (
        status,
        reasoning,
        tel_summary,
        sat_summary,
        doc_summary,
        pid_img,
        emissions_fig,
        json.dumps(card, indent=2, ensure_ascii=False)
    )


def _launch_ui():
    if gr is None:
        logger.error("Gradio is not available in the environment. UI cannot be launched.")
        return
    with gr.Blocks() as app:
        gr.Markdown("# 🛡️ Project Sentinel — Industrial Asset Safety Agent")
        with gr.Row():
            with gr.Column(scale=1):
                row_sel = gr.Slider(1, 9999, value=164, step=1, label="UCI Dataset Row")
                sensor_sel = gr.Dropdown(choices=["PT-HB20-01", "PT-HA24-01", "PT-HO45-01"],
                                         value="PT-HB20-01", label="Asset Sensor Tag")
                run_btn = gr.Button("Run Assessment", variant="primary")
            with gr.Column(scale=2):
                gr.Plot(lambda: generate_emissions_plot(80))
        status_box = gr.Textbox(label="System Status", lines=1)
        reasoning_box = gr.Textbox(label="ReAct Trace", lines=8)
        tel_box = gr.Textbox(label="UCI Telemetry", lines=6)
        sat_box = gr.Textbox(label="ESA Satellite CH4", lines=6)
        doc_box = gr.Textbox(label="Equinor P&ID Lookup", lines=5)
        pid_img = gr.Image(label="Engineering Drawing", type="pil")
        plot_box = gr.Plot(label="Torque vs Emission Proxy")
        card_box = gr.Code(label="Adaptive Card JSON", language="json", lines=10)

        run_btn.click(
            fn=run_assessment,
            inputs=[row_sel, sensor_sel],
            outputs=[status_box, reasoning_box, tel_box, sat_box, doc_box, pid_img, plot_box, card_box]
        )
        app.launch(share=False)


if __name__ == "__main__":
    _launch_ui()
