"""Keep this self-contained directory out of any pytest run rooted elsewhere."""

from pathlib import Path

HERE = Path(__file__).resolve().parent


def pytest_ignore_collect(collection_path, config):
    try:
        root = Path(str(config.rootpath)).resolve()
    except Exception:
        return None
    if root != HERE and HERE in Path(str(collection_path)).resolve().parents:
        return True
    return None
