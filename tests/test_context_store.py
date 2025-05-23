import pytest
from pathlib import Path
from context_store import process_source

class TestFencedBlockBehavior:
    def test_scenario_a_ignores_comments_in_code_blocks(self, tmp_path):
        # Setup mock repo and Markdown file with only a fenced code block containing comments
        repo = tmp_path / "mock_repo"
        repo.mkdir()
        file_path = repo / "scenario_a.md"
        content = (
            "```python\n"
            "# comment inside code block\n"
            "print('hello')\n"
            "x = 42\n"
            "y = 43\n"
            "```\n"
        )
        file_path.write_text(content, encoding="utf-8")

        chunks = []
        meta = []
        process_source(file_path, content, "Markdown", chunks, meta, repo)

        # No chunks or meta entries should be created for comments inside code blocks
        assert chunks == []
        assert meta == []

    def test_scenario_b_headings_outside_code_blocks(self, tmp_path):
        # Setup mock repo and Markdown file with two headings and content
        repo = tmp_path / "mock_repo"
        repo.mkdir()
        file_path = repo / "scenario_b.md"
        content = (
            "# Heading1\n"
            "Line1\n"
            "Line2\n"
            "Line3\n"
            "Line4\n"
            "# Heading2\n"
            "Line5\n"
            "Line6\n"
            "Line7\n"
            "Line8\n"
            "Line9\n"
        )
        file_path.write_text(content, encoding="utf-8")

        chunks = []
        meta = []
        process_source(file_path, content, "Markdown", chunks, meta, repo)

        # Expect two chunks, one per heading
        assert len(chunks) == 2
        assert meta[0]["heading_path"] == "Heading1"
        assert meta[1]["heading_path"] == "Heading2"
        assert chunks[0].startswith("# Heading1")
        assert chunks[1].startswith("# Heading2")

    def test_scenario_c_combined_fenced_and_headings(self, tmp_path):
        # Setup mock repo and a combined Markdown file
        repo = tmp_path / "mock_repo"
        repo.mkdir()
        file_path = repo / "scenario_c.md"
        content = (
            "# Intro\n"
            "Para1\n"
            "Para2\n"
            "Para3\n"
            "Para4\n"
            "```python\n"
            "# inside comment\n"
            "code_line1\n"
            "code_line2\n"
            "```\n"
            "# Next\n"
            "More1\n"
            "More2\n"
            "More3\n"
            "More4\n"
            "More5\n"
        )
        file_path.write_text(content, encoding="utf-8")

        chunks = []
        meta = []
        process_source(file_path, content, "Markdown", chunks, meta, repo)

        # Should only split on the two headings, ignoring the code-block comment
        assert len(chunks) == 2
        assert meta[0]["heading_path"] == "Intro"
        assert meta[1]["heading_path"] == "Next"
        assert chunks[0].startswith("# Intro")
        assert chunks[1].startswith("# Next")
