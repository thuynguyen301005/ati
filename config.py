import os
from pathlib import Path

from dotenv import load_dotenv

# Đọc file .env ở thư mục gốc project (nếu có).
# override=False: biến môi trường thật của hệ thống được ưu tiên hơn file .env.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "")

if not GOOGLE_GEMINI_API_KEY:
    # Khong dau: console Windows (cp1258) khong encode duoc tieng Viet co dau.
    print(
        "[config] CANH BAO: chua co GOOGLE_GEMINI_API_KEY. "
        "Tao file .env tu .env.example va dien key, neu khong moi loi goi Gemini se loi 400."
    )
