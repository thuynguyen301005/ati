from typing import Any, Dict

from services.analysis import (
    merge_dot_graphs,
    render_svg_from_dot,
    review_repo_with_gemini,
    send_to_gemini,
)


def analyze_repository_files(
    files: Dict[str, str],
) -> tuple[Dict[str, Any], Dict[str, str], str | None]:
    file_infos: Dict[str, Dict[str, Any]] = {}
    dot_results: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    for filename, code in files.items():
        result, error = send_to_gemini(filename, code)
        if error:
            file_infos[filename] = {
                "path": filename,
                "status": "error",
                "error": error,
            }
            errors[filename] = error
            continue

        dot_code = result["dot_code"]
        dot_results[filename] = dot_code
        file_infos[filename] = {
            "path": filename,
            "status": "success",
            "dot_code": dot_code,
            "classes": result.get("classes", []),
            "functions": result.get("functions", []),
            "imports": result.get("imports", []),
            "description": result.get("description", ""),
        }

    summary = {
        "processed": len(dot_results),
        "failed": len(errors),
    }
    if not dot_results:
        return {
            "files": file_infos,
            "summary": summary,
            "diagram_svg": None,
            "dot_code": None,
            "review": None,
            "review_error": None,
        }, errors, None

    merged_dot = merge_dot_graphs(dot_results.values())
    svg_data, graphviz_error = render_svg_from_dot(merged_dot)
    review, review_error = review_repo_with_gemini(files)

    return {
        "files": file_infos,
        "summary": summary,
        "diagram_svg": svg_data,
        "dot_code": merged_dot,
        "review": review if review and not review_error else None,
        "review_error": review_error or graphviz_error,
    }, errors, graphviz_error
