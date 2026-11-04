# AI Structura

Code-to-Diagram Generator is a Python Flask-based AI application that includes diagram representation using HTML, CSS, and JavaScript.

## Introduction

CodeStructureViz (AI-Structura) is a tool that supports learning and working with code, allowing you to:

- Select an entire folder containing source code(local folder or Git URL).
- The system uses AI + rules to analyze the code to:
  - Identify classes, functions, modules, APIs, dependencies…
  - Build a system structure model from the code itself.
- Automatically generate:
  - DOT files describing the code structure (for each file).
  - Architecture diagrams (SVG format) showing relationships between parts of the system.

## Installation

### Prerequisites

- Python 3.x
- Flask
- HTML, CSS, and JavaScript
- GitPython

### Setup

1. Clone the repository:

   ```bash
   git clone
   cd F2025_61FIT4ATI_CodeStructureViz
   ```

2. Install GitPython

   ```bash
   pip install GitPython
   ```

3. Download Graphviz

   ```
   - Download Graphviz: https://graphviz.org/download/
   - Install it.
   - Add the Graphviz bin folder to the PATH (if the installer didn't do it automatically).
   ```

4. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

5. Install the required packages:

   ```bash
   pip install -r requirements.txt
   ```

6. Set the Gemini API key:

   ```bash
   cp .env.example .env
   ```

   Open `.env` and replace the placeholder with a real key from
   https://aistudio.google.com/apikey :

   ```
   GOOGLE_GEMINI_API_KEY=AIza...
   ```

   The app loads this file automatically at startup. Without a valid key every
   Gemini call returns `400 API_KEY_INVALID`.

7. Run the Flask application:
   ```bash
   flask run
   ```

## Project structure

```text
web/                 Flask app factory, Blueprints, and web state
  auth.py             Login, registration, and page routes
  specification_generation.py  Requirement validation and generation routes
  specification_projects.py     Project management and chat routes
  specification_artifacts.py    Artifact editing, export, and test routes
  repository_pages.py Repository page route
  repository_analysis_routes.py Local/Git analysis request routes
  repository_api.py   Repository chat, structure, graph, and review APIs
  state.py            In-memory repository analysis results
services/             Database, external clients, and business logic
  repository_analysis.py  Shared local/Git code analysis workflow
  repository_chat.py      Repository-aware Gemini chat
  specification_service.py Specification creation and project workflows
  specification_artifact_service.py Export and generated-test workflows
templates/            Jinja HTML templates
static/               CSS, JavaScript, and images
tests/                Automated tests
app.py                Flask CLI and local development entry point
config.py             Environment and application configuration
```

Routes are grouped by feature in Flask Blueprints. `app.py` remains the
entry point, so `flask run` and `python app.py` continue to work. HTTP handling
stays in `web/`; reusable project and repository workflows live in `services/`.

## Usage

Open your web browser and navigate to `http://127.0.0.1:5000`.
