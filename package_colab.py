#!/usr/bin/env python3
"""Package only the cached offline build inputs for the Colab notebook."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
FILES = [HERE / "build.py", *sorted((HERE / "data").rglob("*")), *sorted((HERE / "assets").rglob("*"))]
with ZipFile(HERE / "colab_bundle.zip", "w", ZIP_DEFLATED, compresslevel=8) as z:
    for path in FILES:
        if path.is_file() and "__pycache__" not in path.parts:
            z.write(path, Path("project_submit") / path.relative_to(HERE))
print(HERE / "colab_bundle.zip")
