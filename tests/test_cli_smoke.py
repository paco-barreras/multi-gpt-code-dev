import subprocess
import pytest
from pathlib import Path
import json
import numpy as np

@pytest.fixture
def minimal_repo(tmp_path):
    # Setup minimal repository with .md and .ipynb files
    repo_root = tmp_path / "minimal_repo"
    repo_root.mkdir()

    # Create .md file for Topic A (Climate Change)
    md_file = repo_root / "example.md"
    md_file.write_text("# Climate Change\nThe environmental impact of carbon emissions is profound.\n", encoding="utf-8")

    # Create .ipynb file for Topic B (Quantum Computing)
    ipynb_file = repo_root / "example.ipynb"
    ipynb_content = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Quantum Computing\nQuantum bits can exist in multiple states at once."]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": ["print('Quantum computing is the future.')"]
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2
    }
    with open(ipynb_file, "w", encoding="utf-8") as f:
        json.dump(ipynb_content, f)

    return repo_root


class TestBuildAndQueryProse:
    def test_build_and_query_prose(self, minimal_repo):
        # Run build-prose command with required arguments
        output_dir = minimal_repo  # the output directory where the .npz file will be saved
        result = subprocess.run(
            ["python", "context_store.py", "build-prose", "--repo", str(minimal_repo), "--output", str(output_dir)],
            capture_output=True, text=True
        )

        # Print debugging output
        print("build-prose stdout:", result.stdout)
        print("build-prose stderr:", result.stderr)

        assert result.returncode == 0  # Ensure command was successful

        # Construct the expected .npz file path using repo name
        npz_file = output_dir / f"{minimal_repo.name}_prose_index.npz"
        
        # Check if the .npz file is created
        assert npz_file.exists(), f"Expected .npz file not found at {npz_file}"

        # Now run query-prose command with a query related to Topic A (Climate Change)
        result = subprocess.run(
            ["python", "context_store.py", "query-prose", "--index", str(npz_file), "--query", "carbon emissions impact on environment", "--k", "1"],
            capture_output=True, text=True
        )

        # Print debugging output
        print("query-prose stdout:", result.stdout)
        print("query-prose stderr:", result.stderr)

        # Ensure query-prose was successful
        assert result.returncode == 0  # Ensure command was successful

        # Parse the JSON output from query-prose
        query_result = json.loads(result.stdout)

        # Check that the chunk returned is related to Topic A (Climate Change)
        expected_output = {
            "heading_path": "Climate Change",
            "snippet": "# Climate Change\nThe environmental impact of carbon emissions is profound.\n"
        }

        # Assert that the expected output is in the query result
        assert any(
            chunk["heading_path"] == expected_output["heading_path"] and
            chunk["snippet"] == expected_output["snippet"]
            for chunk in query_result
        ), f"Expected heading and snippet not found in query result: {query_result}"

        # Additionally, ensure that the chunk related to Topic B (Quantum Computing) is **NOT** returned
        unexpected_output = {
            "heading_path": "Quantum Computing",
            "snippet": "# Quantum Computing\nQuantum bits can exist in multiple states at once."
        }

        assert not any(
            chunk["heading_path"] == unexpected_output["heading_path"] and
            chunk["snippet"] == unexpected_output["snippet"]
            for chunk in query_result
        ), f"Unexpected chunk from Topic B found in query result: {query_result}"
