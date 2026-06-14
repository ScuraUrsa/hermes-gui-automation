# Hermes GUI Automation Infrastructure

Enables Hermes Agent to **see the screen, read text, identify UI elements, click buttons, type text, navigate menus, fill forms, and interact with ANY graphical application** — all autonomously, on a headless Linux VM, without human intervention.

## What This Repository Provides

- **Research Report** — 10 Architectural Decision Records, technology landscape survey across 8 layers, security analysis, performance benchmarks
- **Python Library (`hermes_gui`)** — Modular GUI automation with 4 backends (AT-SPI2, Visual/OCR, VLM, Browser), input layer (mouse/keyboard/clipboard), capture layer (screenshot/window), OCR layer (Tesseract+EasyOCR), vision layer (Florence-2+OmniParser+OpenCV), 8 application adapters
- **Hermes Skill** — `gui-automation` skill teaching Hermes how to use GUI tools effectively
- **Test Suite** — ~100 pytest tests validating every capability against real applications (Firefox, LibreOffice, Nautilus, Gedit, Terminal, Calculator, Evince)
- **GitHub Actions CI/CD** — 5 workflows: continuous testing, staging/production deployment, model updates, health checks
- **Ansible Playbooks** — 10 roles, 9 playbooks provisioning a complete headless GUI VM from bare metal

## Architecture

```
Hermes Agent → hermes_gui library → Backend Selection
  ├── AT-SPI2 Backend (fast path — GTK, Qt, LibreOffice, Firefox)
  ├── Visual Backend (OCR + template matching — any application)
  ├── VLM Backend (Florence-2 + OmniParser — ambiguous cases)
  └── Browser Backend (Playwright — web automation)
       │
       ▼
  Input Layer (mouse, keyboard, clipboard)
  Capture Layer (screenshot, window management)
  OCR Layer (Tesseract 5 + EasyOCR)
  Vision Layer (Florence-2, OmniParser, OpenCV)
  App Adapters (Firefox, LibreOffice, Nautilus, Gedit, Terminal, Calculator, Evince)
       │
       ▼
  Display Server (Xvfb :99 — virtual framebuffer, headless)
```

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/ScuraUrsa/hermes-gui-automation.git
cd hermes-gui-automation

# 2. Deploy the GUI VM
ansible-playbook -i ansible/inventory/staging/hosts.yml ansible/playbooks/gui_vm_full_deploy.yml

# 3. Install the Python library
pip install -e .

# 4. Run tests
pytest -m "not slow and not vlm"  # Fast tests only
pytest -m app                      # Application integration tests

# 5. Use from Hermes
# The gui-automation skill is auto-deployed. Hermes can now:
# - gui_screenshot() → see the screen
# - gui_find("Submit") → find a button
# - gui_click(element) → click it
# - gui_type("Hello") → type text
# - gui_fill_form({"Username": "admin", "Password": "..."}) → fill a form
```

## Repository Structure

```
├── GUI_AUTOMATION_REPORT.md       # Comprehensive research report (60+ pages)
├── hermes_gui/                     # Python library
│   ├── core.py                     # Orchestration, layer selection, fallback
│   ├── types.py                    # Dataclasses: Element, BoundingBox, Window, Screenshot
│   ├── backends/                   # 4 automation backends
│   ├── input/                      # Mouse, keyboard, clipboard
│   ├── capture/                    # Screenshot, window management
│   ├── ocr/                        # Tesseract 5 + EasyOCR
│   ├── vision/                     # Florence-2, OmniParser, OpenCV
│   ├── apps/                       # 8 application adapters
│   └── utils/                      # Geometry, wait conditions, logging
├── tests/                          # ~100 pytest tests (23 modules)
├── ansible/                        # Infrastructure as Code
│   ├── inventory/                  # Production and staging inventories
│   ├── playbooks/                  # 9 deployment playbooks
│   └── roles/                      # 10 Ansible roles
├── .github/workflows/              # 5 CI/CD pipelines
├── skills/gui-automation/          # Hermes skill
└── docs/                           # Research artifacts
```

## License

MIT — see [LICENSE](LICENSE) for details.

## Author

Filip Kaźmierczak & Hermes Orchestrator, 2026
