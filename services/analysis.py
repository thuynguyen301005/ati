import re
import time
import json
from typing import Dict, Tuple, Iterable

import requests
import graphviz

from config import GOOGLE_GEMINI_API_KEY

# === API URL của Gemini ===
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GOOGLE_GEMINI_API_KEY}"
)


def send_to_gemini(filename: str, code: str) -> Tuple[dict | None, str | None]:
    """
    Gửi nội dung file lên Gemini, yêu cầu:
      - Tóm tắt cấu trúc: classes, functions, imports, description.
      - Graphviz DOT cho cấu trúc.

    Trả về:
        (result: dict | None, error: str | None)

    result dạng:
    {
      "dot_code": "...",
      "classes": [ { "name": "...", "methods": [...], "base_classes": [...] }, ...],
      "functions": [ { "name": "...", "params": "...", "description": "..." }, ...],
      "imports": [ "moduleA", "moduleB", ... ],
      "description": "Tóm tắt file"
    }
    """
    headers = {"Content-Type": "application/json"}

    prompt = f"""
You are analyzing a source code file named "{filename}".

1. Understand the structure: modules, imports, classes, methods, functions and how they connect.
2. Generate:
   a) A concise JSON description of the structure.
   b) A Graphviz DOT diagram describing relationships between major elements.

Return your answer in EXACTLY this JSON format, with no extra text before or after:

{{
  "dot_code": "GRAPHVIZ_DOT_HERE",
  "classes": [
    {{
      "name": "ClassName",
      "base_classes": ["Base1", "Base2"],
      "methods": ["method1", "method2"]
    }}
  ],
  "functions": [
    {{
      "name": "function_name",
      "params": "(arg1, arg2)",
      "description": "Short description of what it does"
    }}
  ],
  "imports": ["module1", "module2"],
  "description": "1–3 sentences describing the main purpose of this file"
}}

STRICT RULES:
- Output MUST be valid JSON.
- Do NOT wrap in backticks.
- Do NOT add Markdown.
- Do NOT add any explanation, only the JSON object.
- "dot_code" must be valid Graphviz DOT syntax for a single digraph string.
- Escape quotes inside "dot_code" if necessary.
- Keep the DOT diagram reasonably small: focus only on main modules, classes, and top-level functions.
- Avoid listing every minor helper, trivial utility, or line-level detail in the DOT graph.

---

Here is the file content:

{code}
    """.strip()

    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}

    max_retries = 5
    attempt = 0

    while attempt < max_retries:
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload)

        if response.status_code == 200:
            try:
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

                # 1) Thử parse JSON trực tiếp
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    # 2) Nếu fail, bóc JSON: lấy từ '{' đầu tiên tới '}' cuối cùng
                    start = text.find("{")
                    end = text.rfind("}")
                    if start == -1 or end == -1 or end <= start:
                        raise ValueError("No JSON object found in AI response.")

                    json_str = text[start: end + 1]
                    result = json.loads(json_str)

                if "dot_code" not in result:
                    return None, "AI response missing 'dot_code'."

                # Đảm bảo các key khác tồn tại
                result.setdefault("classes", [])
                result.setdefault("functions", [])
                result.setdefault("imports", [])
                result.setdefault("description", "")

                return result, None

            except Exception as e:
                return None, f"Error parsing AI JSON response: {e}"

        elif response.status_code == 429:
            # Rate limit
            try:
                data = response.json()
                details = data["error"].get("details", [])
                retry_after = 40
                for d in details:
                    if "@type" in d and "RetryInfo" in d["@type"]:
                        delay_str = d.get("retryDelay", "40s")
                        retry_after = int(re.search(r"\d+", delay_str).group(0))
                print(f"[Rate limit] Waiting {retry_after}s before retrying {filename}...")
                time.sleep(retry_after)
            except Exception:
                print("[Rate limit] Waiting 40s (default)...")
                time.sleep(40)
            attempt += 1
            continue

        else:
            return None, f"Error {response.status_code}: {response.text}"

    return None, "Max retries reached after repeated 429 errors."


def merge_dot_graphs(dot_list: Iterable[str]) -> str:
    """
    Gộp nhiều đồ thị DOT thành một đồ thị chung digraph G { ... }.
    """
    merged = ["digraph G {"]
    for dot in dot_list:
        inner = re.search(r"\{(.*)\}", dot, re.DOTALL)
        if inner:
            merged.append(inner.group(1).strip())
    merged.append("}")
    return "\n".join(merged)


def render_svg_from_dot(merged_dot: str) -> tuple[str | None, str | None]:
    """
    Render DOT thành SVG.

    Trả về (svg_data, error_message)
    """
    try:
        dot = graphviz.Source(merged_dot, format="svg")
        svg_data = dot.pipe(format="svg").decode("utf-8")
        return svg_data, None
    except Exception as e:
        return None, str(e)


def review_repo_with_gemini(filename_to_code: Dict[str, str]) -> Tuple[dict | None, str | None]:
    """
    Nhận dict { path: code } của các file trong repo,
    gửi lên Gemini để review lỗi/cải tiến.

    Trả về:
      (review: dict | None, error: str | None)

    review dạng:
    {
      "summary": "Overall review...",
      "issues": [
        {
          "file": "path/to/file.py",
          "line": 42,
          "severity": "error" | "warning" | "style",
          "title": "Nguyên nhân",
          "suggestion": "Gợi ý sửa"
        },
        ...
      ]
    }
    """
    max_chars_per_file = 1500
    sampled_files = []
    for path, code in filename_to_code.items():
        snippet = code[:max_chars_per_file]
        sampled_files.append(f"=== FILE: {path} ===\n{snippet}\n")

    joined_code = "\n\n".join(sampled_files)

    headers = {"Content-Type": "application/json"}

    prompt = f"""
You are a senior code reviewer.

You will receive multiple source files from a small project (partial contents).

Your task:
1. Detect potential bugs, bad practices, or dangerous patterns.
2. Suggest improvements (readability, performance, structure) where relevant.
3. Be concise but specific: reference file names and line numbers if possible.

Return your result as valid JSON only, no extra text.

Format:

{{
  "summary": "Overall, the project ...",
  "issues": [
    {{
      "file": "relative/path/to/file.py",
      "line": 42,
      "severity": "error",
      "title": "Short title of the issue",
      "suggestion": "Concrete suggestion how to fix or improve it"
    }}
  ]
}}

Rules:
- If you find no meaningful issues, return:
  {{
    "summary": "No significant issues found.",
    "issues": []
  }}
- Do NOT add Markdown, backticks, or explanations outside the JSON.
- Be honest: don't invent line numbers if you're not sure; you can use -1.

Here are the files (partial contents):

{joined_code}
    """.strip()

    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}

    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload)
        if response.status_code != 200:
            return None, f"Review API error {response.status_code}: {response.text}"

        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        try:
            review = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("No JSON object found in review response.")

            json_str = text[start: end + 1]
            review = json.loads(json_str)

        review.setdefault("summary", "")
        review.setdefault("issues", [])
        return review, None

    except Exception as e:
        return None, f"Error during review: {e}"
