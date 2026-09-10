import os
import tempfile
import shutil
from typing import Dict, Tuple

from git import Repo as GitRepo  # pip install GitPython
from git.exc import GitCommandError


def load_files_from_directory(root_dir: str) -> Dict[str, str]:
    """
    Đọc tất cả file text từ root_dir thành dict {relative_path: content}.

    Bỏ qua một số thư mục rác như .git, __pycache__, node_modules...
    """
    files: Dict[str, str] = {}
    skip_dirs = {
        '.git', '.hg', '.svn', '__pycache__',
        'node_modules', '.venv', 'venv', '.mypy_cache'
    }

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # filter thư mục
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir)

            try:
                size_bytes = os.path.getsize(full_path)
                # Bỏ qua file quá lớn (200KB) để tránh lỗi
                if size_bytes > 200 * 1024:
                    continue

                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                # Nếu đọc file lỗi thì bỏ qua
                continue

            files[rel_path] = content

    return files


def _human_friendly_git_error(msg: str) -> str:
    """
    Chuyển một số lỗi Git phổ biến thành thông báo thân thiện cho người dùng.
    """
    lower = msg.lower()

    # Repo không tồn tại / URL sai / không có quyền
    if "repository not found" in lower:
        return (
            "Không tìm thấy repository này trên server (Repository not found). "
            "Hãy kiểm tra lại URL, hoặc repo có thể là private mà server không có quyền truy cập."
        )

    # Lỗi xác thực (thường gặp với private repo)
    if "authentication" in lower or "auth failed" in lower or "could not read username" in lower:
        return (
            "Không thể xác thực với Git server. "
            "Repo này có thể là private hoặc cần token/SSH key. "
            "Demo hiện chỉ hỗ trợ public repo. "
            "Với private repo, hãy clone về máy local rồi dùng chế độ 'From local folder'."
        )

    # Lỗi network
    if "could not resolve host" in lower or "connection timed out" in lower:
        return (
            "Không thể kết nối tới Git server (lỗi mạng hoặc host không tồn tại). "
            "Hãy kiểm tra lại URL và kết nối mạng của server."
        )

    # Mặc định: trả về message gốc (nhưng có prefix rõ ràng)
    return f"Git error: {msg}"


def clone_git_repo_and_load_files(git_url: str) -> Tuple[Dict[str, str], str | None]:
    """
    Clone git_url vào thư mục tạm, trả về (files, error).

    files: dict {relative_path: content}
    error: None nếu thành công, hoặc message thân thiện nếu lỗi.

    Lưu ý:
    - Hiện tại demo chỉ hỗ trợ repo public.
    - Với private repo, user nên clone về local rồi dùng 'From local folder'.
    """
    tmp_dir = tempfile.mkdtemp(prefix="deepwiki_git_")

    try:
        # Thử clone repo
        GitRepo.clone_from(git_url, tmp_dir)

        # Đọc file
        files = load_files_from_directory(tmp_dir)
        if not files:
            return {}, (
                "Đã clone được repo nhưng không đọc được file nào "
                "(có thể tất cả file đều quá lớn hoặc không phải text)."
            )
        return files, None

    except GitCommandError as e:
        msg = str(e)
        friendly = _human_friendly_git_error(msg)
        return {}, friendly

    except Exception as e:
        # Lỗi bất ngờ khác
        return {}, f"Failed to clone git repo: {e}"

    finally:
        # Dọn thư mục tạm
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
