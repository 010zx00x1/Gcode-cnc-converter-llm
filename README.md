<div align="center">

# 🚀 G-CODE CNC CONVERTER: FANUC TO SIEMENS 840D

**We don't just translate G-Code. We mathematically prove it.**

[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-React-61DAFB?style=for-the-badge&logo=react)](https://reactjs.org/)
[![Orchestration](https://img.shields.io/badge/Orchestration-LangGraph-FF9900?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

An intelligent, hybrid G-Code converter specifically built to translate **Fanuc CNC programs into Siemens 840D format** with zero geometric hallucinations.

</div>

---

## 🔥 The Moat: Why This Wins

Most AI wrappers just feed text to an LLM and pray it doesn't crash a $500,000 CNC machine. We built an autonomous system with a **Geometric Correction Loop**. 

If the translated toolpath deviates beyond our threshold, the system catches the error, re-prompts the LLM with the exact geometric delta, and re-generates until the math is flawless.

* **Hybrid Translation Engine:** Deterministic mapping for standard commands (fast, cheap) combined with LLM routing for complex logic (smart).
* **Self-Correcting Geometric Validation:** We simulate both source and translated toolpaths (XYZ). If `max_deviation_mm > threshold`, LangGraph triggers a correction node.
* **Zero-Friction Architecture:** FastAPI backend with ThreadPool execution, polled asynchronously by a React/Vite frontend. The UI never freezes.

---

## ⚙️ Tech Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend** | Python, FastAPI | High-performance API and concurrent task execution. |
| **Orchestration**| LangGraph | State machine for the LLM correction loop. |
| **Frontend** | React (Vite) | Asynchronous polling UI for zero-friction user experience. |
| **AI Models** | GPT-4o, Claude, Ollama | Smart parameter injection and logic resolution. |
| **Infra** | Docker Compose | One-click reproducible environments. |

---


## 🚀 Quick Start

1. Clone the repository to your local machine:
   ```bash
   git clone [https://github.com/010zx00x1/Gcode-cnc-converter-llm.git](https://github.com/010zx00x1/Gcode-cnc-converter-llm.git)
   cd Gcode-cnc-converter-llm
Copy the environment variables file and add your API keys:

Bash
cp .env.example .env
Spin up the machine using Docker:

Bash
docker-compose up --build
Open http://localhost:5173 in your browser and upload your Fanuc .mpf or .nc file.

---

## 🧠 Architecture Flow
<div align="center">
<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/745504a9-c41d-4af3-b4aa-ed75a0d3c22d" />

</div>

---

## 🗺️ The Roadmap: Horizontal Scaling
Right now, we are ruthlessly focused on one thing: Fanuc to Siemens 840D. We are building the absolute best, most mathematically sound converter for this specific pipeline.

However, the core LangGraph architecture (Parse -> Intermediate Representation -> LLM -> Simulate -> Correct) is completely format-agnostic. Once we achieve total dominance and zero-friction execution in the Fanuc/Siemens space, our roadmap includes horizontal expansion to support:

Heidenhain (TNC 640, etc.)

Haas

Mazak (Mazatrol)

Custom / Proprietary G-Code Dialects

The engine is built to scale. The current focus is perfection.


