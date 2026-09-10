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

6. Run the Flask application:
   ```bash
   flask run
   ```

## Usage

Open your web browser and navigate to `http://127.0.0.1:5000`.
