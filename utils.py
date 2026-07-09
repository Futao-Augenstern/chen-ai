"""共享工具函数。

提供原子写入等通用功能，不依赖任何外部库。
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def atomic_write_json(filepath: Path, data: Any, indent: int = 2) -> None:
    """原子写入 JSON 文件，避免写入过程中断导致数据损坏。

    在目标目录创建临时文件后 os.replace，同一文件系统保证原子性。
    跨文件系统时回退到 shutil.move（非原子但可靠）。
    并发写入时自动重试（最多 3 次）。

    Args:
        filepath: 目标文件路径。
        data: 要写入的数据（必须可 JSON 序列化）。
        indent: JSON 缩进空格数，默认 2。
    """
    import shutil

    dirpath = filepath.parent
    dirpath.mkdir(parents=True, exist_ok=True)
    fd, tmppath = tempfile.mkstemp(dir=str(dirpath), suffix=".tmp", prefix=".atomic_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        for attempt in range(3):
            try:
                os.replace(tmppath, str(filepath))
                return
            except OSError:
                if attempt < 2:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                try:
                    shutil.move(tmppath, str(filepath))
                except OSError:
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=indent)
                return
    except Exception:
        try:
            os.unlink(tmppath)
        except OSError:
            pass
        raise