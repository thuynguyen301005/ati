"""
Lớp gọi Gemini dùng chung: giữ model ID ở một chỗ duy nhất và tự retry
các lỗi tạm thời (429 quá quota, 5xx model quá tải).
"""
import random
import re
import time
from typing import Any, Dict, Tuple

import requests

from config import GOOGLE_GEMINI_API_KEY

# Đổi model ở đây là đổi cho toàn bộ ứng dụng.
GEMINI_MODEL = "gemini-3.6-flash"

GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GOOGLE_GEMINI_API_KEY}"
)

# Các mã lỗi đáng thử lại: hết quota tạm thời, hoặc model đang quá tải.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_HEADERS = {"Content-Type": "application/json"}


def _retry_delay_from_body(response: requests.Response, fallback: float) -> float:
    """Ưu tiên RetryInfo Google trả về; không có thì dùng fallback."""
    try:
        for detail in response.json()["error"].get("details", []):
            if "RetryInfo" in detail.get("@type", ""):
                found = re.search(r"\d+", detail.get("retryDelay", ""))
                if found:
                    return float(found.group(0))
    except Exception:
        pass
    return fallback


def post_gemini(
    payload: Dict[str, Any],
    label: str = "",
    timeout: int = 120,
    max_retries: int = 5,
) -> Tuple[requests.Response | None, str | None]:
    """
    Gọi Gemini, tự thử lại khi gặp lỗi tạm thời.

    Trả về (response 200, None) hoặc (None, thông báo lỗi).
    """
    last_error = "Unknown error"

    for attempt in range(max_retries):
        try:
            response = requests.post(
                GEMINI_API_URL, headers=_HEADERS, json=payload, timeout=timeout
            )
        except requests.RequestException as exc:
            last_error = f"Network error: {exc}"
            if attempt == max_retries - 1:
                break
            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))
            continue

        if response.status_code == 200:
            return response, None

        if response.status_code not in RETRYABLE_STATUS:
            # Lỗi thật (key sai, model không tồn tại, payload hỏng) - thử lại vô ích.
            return None, f"Gemini API error {response.status_code}: {response.text}"

        last_error = f"Gemini API error {response.status_code}: {response.text}"
        if attempt == max_retries - 1:
            break

        # 429 thường kèm RetryInfo; 5xx thì lùi theo cấp số nhân.
        fallback = min(2 ** attempt, 30) + random.uniform(0, 1)
        wait = _retry_delay_from_body(response, fallback) if response.status_code == 429 else fallback
        # Log khong dau: console Windows (cp1258) khong encode duoc tieng Viet co dau.
        print(
            f"[Gemini {response.status_code}] {label or 'request'}: "
            f"retry sau {wait:.1f}s (lan {attempt + 1}/{max_retries})"
        )
        time.sleep(wait)

    return None, f"{last_error} (da thu {max_retries} lan)"
