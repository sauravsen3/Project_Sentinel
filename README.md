# Project_Sentinel
# Project Sentinel 🛡️

> **Agents League Hackathon 2026** — *Reasoning Agents Track*
>
> An autonomous mechatronics agent leveraging Microsoft IQ to safeguard asset integrity, optimise engineering safety, and eliminate fugitive emissions on heavy energy infrastructure.

---

## 📝 Executive Summary
Project Sentinel is an intelligent, autonomous Digital Twin Agent engineered for heavy energy infrastructure, such as offshore platforms and hydrogen production facilities. Built by a solo mechatronics engineer, the system ingests real-time mechanical sensor telemetry and autonomously cross-references it with complex engineering schematics. This allows the agent to predict structural failures, eliminate fugitive greenhouse gas emissions, and actively protect the workforce on shift without human lag.

---

## ⚠️ The Problem
In large-scale energy operations, equipment degradation and microscopic gas leaks pose severe environmental and human safety risks. When anomalies occur, control room operators and field engineers face extreme cognitive overload. They are often forced to manually hunt through thousands of pages of static PDF blueprints and Piping and Instrumentation Diagrams (P&IDs) to locate critical isolation workflows. 

Minutes wasted reading documentation during an active failure can mean the difference between a minor patch and a catastrophic HSE (Health, Safety, and Environment) incident.



     ### Technical Architecture & Microsoft IQ Integration
Project Sentinel coordinates three distinct intelligence layers to solve complex engineering issues:

* **Fabric IQ (The Asset Graph):** Ingests raw time-series mechatronics data (vibration profiles, temperatures, rotational speeds, and pressures) and maps it to a semantic model of the physical facility. The agent instantly understands exactly *where* an anomalous component sits within the broader process loop and its structural dependencies.
* **Foundry IQ (The Engineering Brain):** Houses the platform's verified Piping and Instrumentation Diagrams (P&IDs) and System Control Diagrams (SCDs). When Fabric IQ flags an anomalous threshold, Foundry IQ reasons over the strict automation logic of the schematics to generate zero-hallucination, cited, and step-by-step physical isolation procedures.
* **Work IQ (The Operational Dispatch):** Connects the technical solution back to the human element. It checks active team schedules and engineering safety certifications via Microsoft 365 Copilot, instantly dispatching the precise mechanical fix and isolation checklist directly to the mobile device of the qualified technician closest to the hazard.

---

## 📊 Data Sources Utilised
This project relies on verified, public heavy-industry data to ensure operational realism:
1. **Equinor Huldra Platform Schematics:** Used to feed P&IDs and System Control Diagrams into Foundry IQ for exact engineering logic extraction.
2. **AI4I 2020 Predictive Maintenance Dataset:** Utilised to simulate real-time mechatronics sensor streams tracking rotational speed, torque, tool wear, and thermal stress.

---

## 🏗️ Repository Structure
```text
project-sentinel/
├── README.md               # Project documentation
├── data/
│   ├── mock_telemetry.csv  # Sample time-series sensor logs
│   └── schematics/         # Sample Huldra PDF engineering diagrams
├── src/
│   ├── __init__.py
│   ├── telemetry_scan.py   # Script to parse data and detect anomalies
│   └── reasoning_engine.py # Core Python agent querying the indexed blueprints
├── requirements.txt        # Project dependencies
└── run.py                  # Main execution script for the prototype demo
---

## 💡 The Solution: Project Sentinel
Project Sentinel bridges the gap between hardware telemetry and operational intelligence. Using real-world data from the Huldra platform technical schematics and industrial sensor logs, the agent functions as an automated safety layer that acts before mechanical failures become critical.
