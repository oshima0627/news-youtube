"""python scripts/X.py 形式で起動できることを守るテスト。

タスクスケジューラや run_daily.py は `python scripts/X.py` の形でCLIを起動する。
この形式だと sys.path[0] が scripts/ になりリポジトリルートが乗らないため、
各CLIが `from scripts.* import ...` する前に sys.path へルートを足していないと
`ModuleNotFoundError` で即死する。import だけを見るテストでは検知できないため、
実際にサブプロセスで起動して終了コードを見る。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 新しいCLIを作ったらここに足すこと。
# python scripts/X.py 形式で起動できないと定期実行が落ちる。
CLI_ENTRYPOINTS = (
    "collect_news.py",
    "verify_source.py",
    "fetch_photo.py",
    "write_script.py",
    "narrate.py",
    "build_short.py",
    "upload_youtube.py",
    "unpublish.py",
    "run_daily.py",
)


@pytest.mark.parametrize("script", CLI_ENTRYPOINTS)
def test_python_scriptsXpy形式でhelpが起動できる(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, f"scripts/{script}", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        # 明示しないと Windows では cp932 でデコードされ、失敗時の stderr
        # （日本語）が読めないうえ EncodingWarning が出る。
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"scripts/{script} が python scripts/{script} 形式で起動できません。"
        f"stderr:\n{proc.stderr}"
    )
