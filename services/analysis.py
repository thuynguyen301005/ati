import re
import json
from typing import Dict, Tuple, Iterable

import graphviz

# GEMINI_API_URL được re-export để app.py tiếp tục import từ đây.
from services.gemini_client import GEMINI_API_URL, post_gemini


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

    response, api_error = post_gemini(payload, label=filename)
    if api_error or response is None:
        return None, api_error

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

    response, api_error = post_gemini(payload, label="repo review")
    if api_error or response is None:
        return None, api_error

    try:
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
