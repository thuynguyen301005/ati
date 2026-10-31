import os
from pathlib import Path

from dotenv import load_dotenv

# Đọc file .env ở thư mục gốc project (nếu có).
# override=False: biến môi trường thật của hệ thống được ưu tiên hơn file .env.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "")

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "instance" / "specforge.db"))

# Khoa ky session dang nhap. Khong dat trong .env thi moi lan khoi dong lai server
# se tao khoa moi va moi nguoi bi dang xuat.
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets

    SECRET_KEY = secrets.token_hex(32)
    print("[config] CANH BAO: chua co SECRET_KEY trong .env, dang dung khoa tam thoi.")

if not GOOGLE_GEMINI_API_KEY:
    # Khong dau: console Windows (cp1258) khong encode duoc tieng Viet co dau.
    print(
        "[config] CANH BAO: chua co GOOGLE_GEMINI_API_KEY. "
        "Tao file .env tu .env.example va dien key, neu khong moi loi goi Gemini se loi 400."
    )
