from typing import Any, Dict, List

from services.gemini_client import post_gemini


def chat_about_repo_with_gemini(
    repo: Dict[str, Any],
    question: str,
    history: List[Dict[str, Any]],
) -> tuple[str | None, str | None]:
    """
    Answer a question using the repository review, summary, and file list.

    Returns the answer and an error, if one occurred.
    """
    try:
        context_parts = []

        if repo.get("review"):
            context_parts.append("AI review summary for this repo:\n" + str(repo["review"]))

        summary = repo.get("summary") or {}
        context_parts.append(
            "Repo summary: processed {processed} files, failed {failed} files.".format(
                processed=summary.get("processed", 0),
                failed=summary.get("failed", 0),
            )
        )

        files_dict = repo.get("files", {})
        file_names = list(files_dict.keys())
        if file_names:
            context_parts.append(
                "Main files in this repo:\n"
                + "\n".join(f"- {name}" for name in file_names[:50])
            )

        system_instr = (
            "You are a senior software engineer who deeply understands this code repository. "
            "Use the provided context about the project (review notes, summary, file list) to answer user questions. "
            "Focus on concrete, practical suggestions for improvements: architecture, readability, testing, "
            "performance, security, and maintainability. If something is not explicitly in the context, "
            "say that clearly and answer using general best practices.\n\n"
            "Repository context:\n"
            + "\n\n".join(context_parts)
        )

        contents = [{
            "role": "user",
            "parts": [{"text": system_instr}],
        }]

        for turn in history:
            text = (turn.get("content") or "").strip()
            if not text:
                continue
            role = "user" if turn.get("role") == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": text}],
            })

        contents.append({
            "role": "user",
            "parts": [{"text": question}],
        })

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.4,
                "topP": 0.9,
                "maxOutputTokens": 1024,
            },
        }

        response, api_error = post_gemini(body, label="repo chat", timeout=60)
        if api_error or response is None:
            return None, api_error

        data = response.json()
        candidates = data.get("candidates")
        if not candidates:
            return None, "No candidates returned from Gemini"

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        answer_chunks = [
            str(part["text"])
            for part in parts
            if isinstance(part, dict) and "text" in part
        ]
        answer = "".join(answer_chunks).strip()
        if not answer:
            return None, f"Empty response text from Gemini. Raw: {data}"

        return answer, None

    except Exception as error:
        print("Gemini chat error:", repr(error))
        return None, str(error)
