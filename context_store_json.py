import json
import ast
import sys
from pathlib import Path

# ---------- AST Helper Functions ----------

def _get_ast_node_source_segment(source_lines, node):
    """
    Extracts the source code segment for an AST node, including decorators.
    Tries to dedent the segment relative to its actual definition line.

    Args:
        source_lines (list[str]): A list of strings, where each string is a line of source code.
        node (ast.AST): The AST node for which to extract the source segment.

    Returns:
        str: The extracted source code segment as a string.
    """
    if not (hasattr(node, 'lineno') and hasattr(node, 'end_lineno')):
        try: return ast.unparse(node)
        except: return f"# Error: Could not unparse {getattr(node, 'name', 'unknown_node')}"

    start_line_idx = node.lineno - 1
    end_line_idx = node.end_lineno

    if hasattr(node, 'decorator_list') and node.decorator_list:
        first_decorator = node.decorator_list[0]
        if hasattr(first_decorator, 'lineno'):
            decorator_start_line_idx = first_decorator.lineno - 1
            if decorator_start_line_idx < start_line_idx:
                start_line_idx = decorator_start_line_idx
    
    if start_line_idx < 0 or end_line_idx > len(source_lines):
        try: return ast.unparse(node)
        except: return f"# Error: Could not reliably get source for {getattr(node, 'name', 'unknown_node')}"

    segment_lines = source_lines[start_line_idx:end_line_idx]
    
    actual_def_line_in_segment_idx = (node.lineno - 1) - start_line_idx
    if 0 <= actual_def_line_in_segment_idx < len(segment_lines):
        first_def_line = segment_lines[actual_def_line_in_segment_idx]
        indentation = len(first_def_line) - len(first_def_line.lstrip())
        if indentation > 0:
            can_dedent = True
            for line_to_check in segment_lines:
                if line_to_check.strip() and not line_to_check.startswith(' ' * indentation):
                    can_dedent = False
                    break
            if can_dedent:
                dedented_lines = [line[indentation:] for line in segment_lines]
                return "".join(dedented_lines)
                
    return "".join(segment_lines)


def _extract_ast_chunks_from_file(py_file_path, repo_root_path):
    """
    Parses a Python file and yields comprehensive dictionaries for functions and classes.
    Each dictionary includes metadata, docstring, full source_code, and a multi-line signature.

    Args:
        py_file_path (pathlib.Path): Path to the Python file to parse.
        repo_root_path (pathlib.Path): Path to the root of the repository for relative path calculation.

    Yields:
        Iterator[dict[str, any]]: An iterator of dictionaries, each representing an AST chunk.
    """
    try:
        file_content = py_file_path.read_text(encoding="utf-8", errors="ignore")
        source_lines = file_content.splitlines(True)
        tree = ast.parse(file_content, filename=str(py_file_path))
    except Exception:
        return
    
    rel_path_str = str(py_file_path.relative_to(repo_root_path))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            source_code_snippet = _get_ast_node_source_segment(source_lines, node)
            if not source_code_snippet or source_code_snippet.startswith("# Error:"):
                continue

            sig_lines_extracted = []
            snippet_lines_for_sig = source_code_snippet.splitlines(True)
            
            for line in snippet_lines_for_sig:
                stripped_line = line.lstrip()
                if stripped_line.startswith("@"):
                    sig_lines_extracted.append(line)
                elif stripped_line.startswith(("def ", "async def ", "class ")):
                    sig_lines_extracted.append(line)
                    break
            
            signature_text = ""
            if sig_lines_extracted:
                first_sig_line = sig_lines_extracted[0].lstrip()
                signature_text = first_sig_line + "".join(sig_lines_extracted[1:])

            yield {
                "file_path": rel_path_str,
                "element_name": node.name,
                "element_type": node.__class__.__name__,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "docstring": ast.get_docstring(node, clean=False) or "",
                "signature": signature_text.strip(),
                "source_code": source_code_snippet,
            }

# ---------- JSON Index Building & Querying ----------

def build_json_indices(repo_path_str, output_dir_str):
    """
    Scans a Python repository, extracts AST chunks, and saves two JSON files:
    - <repo_name>_signatures.json: Contains public (non-underscore-prefixed) elements' signatures and metadata.
    - <repo_name>_fullsource.json: Contains all extracted elements' full source code and metadata.
    Files are saved to the specified output directory.

    Args:
        repo_path_str (str | pathlib.Path): Path to the root directory of the Python repository.
        output_dir_str (str | pathlib.Path): Directory to save the generated JSON index files.
    """
    repo_path = Path(repo_path_str).resolve()
    output_path = Path(output_dir_str).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    repo_name = repo_path.name
    signatures_list = []
    fullsource_list = []

    py_files = [p for p in repo_path.rglob("*.py") if not any(ex in p.parts for ex in
                ['.git', '.vscode', '.idea', '__pycache__', 'node_modules', 'build', 'dist',
                 'venv', 'env', '.env', 'site-packages', '.ipynb_checkpoints'])]

    for py_file in py_files:
        try:
            for chunk in _extract_ast_chunks_from_file(py_file, repo_path):
                # Add to fullsource_list unconditionally
                fullsource_list.append({
                    "file_path": chunk["file_path"],
                    "element_name": chunk["element_name"],
                    "element_type": chunk["element_type"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                    "docstring": chunk["docstring"],
                    "source_code": chunk["source_code"],
                })

                # Add to signatures_list only if not an internal element
                # (name doesn't start with '_' or is a dunder method which is usually public)
                if not (chunk["element_name"].startswith("_") and \
                        not (chunk["element_name"].startswith("__") and chunk["element_name"].endswith("__"))):
                    signatures_list.append({
                        "file_path": chunk["file_path"],
                        "element_name": chunk["element_name"],
                        "element_type": chunk["element_type"],
                        "start_line": chunk["start_line"],
                        "end_line": chunk["end_line"],
                        "docstring": chunk["docstring"],
                        "signature": chunk["signature"],
                    })
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"Warning: Skipping file {py_file} due to error: {e}", file=sys.stderr)
            continue
        
    sig_file_path = output_path / f"{repo_name}_signatures.json"
    full_file_path = output_path / f"{repo_name}_fullsource.json"
    
    with open(sig_file_path, "w", encoding="utf-8") as f:
        json.dump(signatures_list, f, ensure_ascii=False, indent=2)
    with open(full_file_path, "w", encoding="utf-8") as f:
        json.dump(fullsource_list, f, ensure_ascii=False, indent=2)
        
    print(f"JSON indices exported to:\n- {sig_file_path.resolve()}\n- {full_file_path.resolve()}", file=sys.stderr)


def query_json_file(query_str, index_file_path_str, k=3):
    """
    Queries a JSON index file (either signatures or full source) for relevant code elements.
    Search is performed on 'element_name' and 'docstring'.
    The structure of returned elements depends on the input index file.

    Args:
        query_str (str): Search query string.
        index_file_path_str (str | pathlib.Path): Path to the JSON index file to query.
        k (int, optional): Number of top results to return. Defaults to 3.

    Returns:
        list[dict[str, any]]: A list of dictionaries, each representing a matching code element.
    """
    index_path = Path(index_file_path_str)
    if not index_path.is_file():
        print(f"Error: Index file not found at {index_path}", file=sys.stderr)
        return []

    with open(index_path, encoding="utf-8") as f:
        indexed_elements = json.load(f)

    if not indexed_elements:
        return []

    query_tokens = {token.lower() for token in query_str.split() if token}
    if not query_tokens:
        return []

    scored_matches = []
    for element in indexed_elements:
        name_to_search = element.get("element_name", "").lower()
        docstring_to_search = element.get("docstring", "").lower()
        search_text = f"{name_to_search} {docstring_to_search}"
        
        hits = sum(1 for token in query_tokens if token in search_text)
        
        if hits > 0:
            start_line = element.get("start_line", 0)
            scored_matches.append((hits, start_line, element))

    scored_matches.sort(key=lambda x: (-x[0], x[1]))

    results = []
    for _, _, element_data in scored_matches[:k]:
        result_item = {
            "file": element_data.get("file_path"),
            "element_name": element_data.get("element_name"),
            "element_type": element_data.get("element_type"),
            "lines": f"{element_data.get('start_line', '?')}-{element_data.get('end_line', '?')}",
            "docstring": element_data.get("docstring", ""),
        }
        if "signature" in element_data:
            result_item["signature"] = element_data["signature"]
        if "source_code" in element_data:
            result_item["snippet"] = element_data["source_code"]
        
        results.append(result_item)
        
    return results

# ---------- Command-Line Interface ----------

def main_cli():
    """Runs the command-line interface for building or querying JSON indices."""
    parser = argparse.ArgumentParser(
        description="Build or query lightweight JSON-based context indices for Python codebases."
    )
    subparsers = parser.add_subparsers(dest="command", required=True,
                                     help="Action to perform: 'build' or 'query'.")

    build_cmd_parser = subparsers.add_parser("build",
                                          help="Scan a Python repository and create JSON index files.")
    build_cmd_parser.add_argument("--repo", type=str, required=True,
                                  help="Path to the root directory of the Python repository.")
    build_cmd_parser.add_argument("--output-dir", type=str, default=".",
                                  help="Directory to save the generated JSON index files (e.g., my_repo_signatures.json). Defaults to current directory.")

    query_cmd_parser = subparsers.add_parser("query",
                                         help="Query a JSON index file for relevant code elements.")
    query_cmd_parser.add_argument("--index", type=str, required=True,
                                  help="Path to the JSON index file to query (either _signatures.json or _fullsource.json).")
    query_cmd_parser.add_argument("--query", type=str, required=True,
                                  help="Search query string (searches element names and docstrings).")
    query_cmd_parser.add_argument("--k", type=int, default=3,
                                  help="Number of top results to return (default: 3).")

    argv = sys.argv[1:]
    if not argv and sys.stdin.isatty(): 
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    args = parser.parse_args(argv if argv else None)

    if args.command == "build":
        build_json_indices(args.repo, args.output_dir)
    elif args.command == "query":
        query_results = query_json_file(args.query, args.index, args.k)
        if query_results:
            print(json.dumps(query_results, ensure_ascii=False, indent=2))
        else:
            print("No matching results found.", file=sys.stderr)

if __name__ == "__main__":
    import argparse 
    main_cli()