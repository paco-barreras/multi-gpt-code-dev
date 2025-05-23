# tests/test_notebook_chunking.py

import shutil
from pathlib import Path

import numpy as np
import pytest

from context_store import build_prose_index

class TestNotebookChunking:
    def test_notebook_chunking_integration(self, tmp_path):
        # Prepare a temporary repo and copy the fixture notebook into it
        src_nb = Path(__file__).parent / "data" / "prose_repo" / "fixture_notebook.ipynb"
        repo_root = tmp_path / "prose_repo"
        notebooks_dir = repo_root / "notebooks"
        notebooks_dir.mkdir(parents=True, exist_ok=True)
        dest_nb = notebooks_dir / "fixture_notebook.ipynb"
        shutil.copy(src_nb, dest_nb)

        # Run the prose-index builder
        index_file = tmp_path / "prose_idx.npz"
        build_prose_index(repo_root, index_file)

        # Load and inspect the resulting index
        npz = np.load(str(index_file), allow_pickle=True)
        texts = npz["texts"]
        metadata = npz["metadata"]

        # Expect exactly three chunks from the three heading cells
        assert len(texts) == 3
        assert len(metadata) == 3

        # Validate heading_path metadata and element_type for each chunk
        expected_paths = [
            "Top Level",
            "Top Level > Subsection",
            "Top Level > Subsection > Deep Section"
        ]
        actual_paths = [md["heading_path"] for md in metadata]
        assert actual_paths == expected_paths

        for md in metadata:
            assert md["element_type"] == "Notebook"

        # Ensure excluded content did not leak into any chunk
        combined = "\n".join(texts)
        assert "%timeit" not in combined
        assert "!echo" not in combined
        assert "ignored cell" not in combined.lower()
