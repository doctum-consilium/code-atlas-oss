#!/usr/bin/env python3
"""Prepare a small real corpus for the end-to-end tests (CI without GPU).

Creates a sample git repository, writes its manifest into ``$CODE_ATLAS_DATA/corpus.json`` and
indexes it with the fake embedder (``atlas index --fake``). None of your repositories is read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests.conftest import SAMPLE_FILES, make_repo, manifest_for  # noqa: E402


def main() -> int:
    data = Path(os.environ["CODE_ATLAS_DATA"])
    data.mkdir(parents=True, exist_ok=True)
    repo = data / "e2e-corpus" / "sample"
    if not repo.exists():
        make_repo(repo.parent, "sample", SAMPLE_FILES)
    manifest = manifest_for(repo, "acme/sample", SAMPLE_FILES)
    (data / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["uv", "run", "atlas", "index", "--fake"], cwd=ROOT / "backend", check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
