# context_store.py
"""
AST-based Dense-index helper for codebases.

Build Index CLI:
  python context_store.py build --repo <src_dir> --index <index_file.npz> \
                                [--model intfloat/e5-base-v2]

Query Index CLI:
  python context_store.py query --index <index_file.npz> --query "<your_query_string>" \
                                [--k 3] [--max_tokens 1500] [--model intfloat/e5-base-v2]

Import for programmatic querying:
  from context_store import get_code_context
"""
from __future__ import annotations

import argparse
import ast
import gc
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Iterator

import numpy as np
import torch
# sentence_transformers is imported only within functions that use it.

# ---------------------------------------------------------------------
DEFAULT_MODEL: str = "intfloat/e5-base-v2"

_CACHED_INDICES: Dict[Path, Tuple[torch.Tensor, List[Dict[str, Any]]]] = {}
_CACHED_MODELS: Dict[str, Any] = {}
# ---------------------------------------------------------------------

def _get_ast_node_source_segment(source_lines: List[str], node: ast.AST) -> str | None:
    if not (hasattr(node, 'lineno') and hasattr(node, 'end_lineno')):
        return None
    start_line_idx = node.lineno - 1
    end_line_idx = node.end_lineno
    if hasattr(node, 'decorator_list') and node.decorator_list:
        first_decorator = node.decorator_list[0]
        if hasattr(first_decorator, 'lineno'):
            decorator_start_line_idx = first_decorator.lineno - 1
            if decorator_start_line_idx < start_line_idx:
                start_line_idx = decorator_start_line_idx
    if start_line_idx < 0 or end_line_idx > len(source_lines):
        try: return ast.unparse(node) # Fallback for Python 3.9+
        except: return f"# Error: Could not reliably get source for {getattr(node, 'name', 'unknown_node')}"
    segment_lines = source_lines[start_line_idx:end_line_idx]
    actual_def_line_in_segment_idx = (node.lineno - 1) - start_line_idx
    if 0 <= actual_def_line_in_segment_idx < len(segment_lines):
        first_def_line = segment_lines[actual_def_line_in_segment_idx]
        indentation = len(first_def_line) - len(first_def_line.lstrip())
        dedented_lines = [line[indentation:] if line.startswith(' ' * indentation) else line for line in segment_lines]
        return "".join(dedented_lines)
    return "".join(segment_lines)

def _extract_ast_chunks_from_file(py_file_path: Path, repo_root_path: Path) -> Iterator[Dict[str, Any]]:
    try:
        file_content = py_file_path.read_text(encoding="utf-8", errors="ignore")
        source_lines = file_content.splitlines(True)
        tree = ast.parse(file_content, filename=str(py_file_path))
    except Exception as e:
        # print(f"Info: Could not parse AST for {py_file_path}, skipping: {e}", file=sys.stderr) # Optional: for debugging
        return
    file_rel_path_str = str(py_file_path.relative_to(repo_root_path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            source_code_snippet = _get_ast_node_source_segment(source_lines, node)
            if source_code_snippet:
                yield {
                    "file_path": file_rel_path_str, "element_name": node.name,
                    "element_type": node.__class__.__name__, "start_line": node.lineno,
                    "end_line": node.end_lineno, "docstring": ast.get_docstring(node) or "",
                    "source_code": source_code_snippet
                }

def _get_sentence_transformer_model(model_name: str):
    if model_name not in _CACHED_MODELS:
        from sentence_transformers import SentenceTransformer
        print(f"Info: Loading SentenceTransformer model: {model_name}...", file=sys.stderr)
        _CACHED_MODELS[model_name] = SentenceTransformer(model_name, device="cpu")
        print(f"Info: Model {model_name} loaded.", file=sys.stderr)
    return _CACHED_MODELS[model_name]

def _embed_texts_batch(texts: List[str], model_name: str, is_query: bool = False) -> np.ndarray:
    if not texts: return np.array([])
    texts_to_embed = [f"query: {text}" for text in texts] if is_query else texts
    show_progress = not is_query # Show progress only for bulk indexing
    model = _get_sentence_transformer_model(model_name)
    # print(f"Info: Embedding {len(texts_to_embed)} {'queries' if is_query else 'chunks'} with {model_name}...", file=sys.stderr) # Optional
    return model.encode(texts_to_embed, batch_size=32 if not is_query else 1,
                        show_progress_bar=show_progress, normalize_embeddings=True)

def build_index(repo_root_path: str | Path, index_output_path: str | Path, model_name: str = DEFAULT_MODEL):
    repo_root, index_file = Path(repo_root_path).resolve(), Path(index_output_path).resolve()
    if not repo_root.is_dir(): raise FileNotFoundError(f"Repo root not found: {repo_root}")
    all_src_texts, all_meta = [], []
    print(f"Info: Scanning Python files in: {repo_root} for AST chunking...", file=sys.stderr)
    py_files = [p for p in repo_root.rglob("*.py") if not any(ex in p.parts for ex in
                ['.git', '.vscode', '.idea', '__pycache__', 'node_modules', 'build', 'dist',
                 'venv', 'env', '.env', 'site-packages', '.ipynb_checkpoints', 'tests', 'test', 'docs/_build'])] # Common exclusions
    print(f"Info: Found {len(py_files)} Python files to process.", file=sys.stderr)
    for py_path in py_files:
        # print(f"Info: Processing for AST chunks: {py_path.relative_to(repo_root)}", file=sys.stderr) # Optional
        for chunk_dict in _extract_ast_chunks_from_file(py_path, repo_root):
            all_src_texts.append(chunk_dict["source_code"])
            all_meta.append(chunk_dict)
    if not all_src_texts:
        print("Warning: No AST chunks found to index. Creating an empty index.", file=sys.stderr)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(index_file, embeddings=np.array([]), meta=np.array([], dtype=object))
        print(f"Info: Empty index written to {index_file}", file=sys.stderr)
        return
    embeddings = _embed_texts_batch(all_src_texts, model_name, is_query=False)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(index_file, embeddings=embeddings, meta=np.array(all_meta, dtype=object))
    print(f"✓ Index with {len(all_meta)} AST chunks written to {index_file}", file=sys.stderr)

def _load_index_from_file(index_file_path: Path) -> Tuple[torch.Tensor, List[Dict[str, Any]]]:
    # print(f"Info: Loading AST-based index from: {index_file_path}", file=sys.stderr) # Optional
    data = np.load(index_file_path, allow_pickle=True)
    embeds_np, meta_np = data.get("embeddings"), data.get("meta")
    if embeds_np is None or meta_np is None: raise ValueError(f"Index missing 'embeddings' or 'meta': {index_file_path}")
    meta_list = [dict(item) for item in meta_np] # Ensure it's a list of dicts
    # print(f"Info: Index {index_file_path} loaded. Embeddings: {embeds_np.shape}, Meta items: {len(meta_list)}", file=sys.stderr) # Optional
    return torch.tensor(embeds_np, dtype=torch.float32), meta_list

def get_code_context(query: str, index_file_path: str | Path, k: int = 3,
                     max_tokens: int = 2000, query_model_name: str = DEFAULT_MODEL) -> List[Dict[str, Any]]:
    idx_path = Path(index_file_path).resolve()
    if idx_path not in _CACHED_INDICES:
        if not idx_path.exists(): raise FileNotFoundError(f"Index file not found: {idx_path}")
        _CACHED_INDICES[idx_path] = _load_index_from_file(idx_path)
    embeds_tensor, meta_list = _CACHED_INDICES[idx_path]
    if embeds_tensor.nelement() == 0: return []
    q_embed_np = _embed_texts_batch([query], query_model_name, is_query=True)[0]
    q_tensor = torch.tensor(q_embed_np, dtype=torch.float32).to(embeds_tensor.device)
    if embeds_tensor.ndim == 1: embeds_tensor = embeds_tensor.unsqueeze(0)
    if q_tensor.ndim > 1: q_tensor = q_tensor.squeeze()
    if embeds_tensor.shape[0] == 0 or embeds_tensor.shape[1] != q_tensor.shape[0]:
        # print(f"Warning: Dim mismatch or empty embeds. Embeds: {embeds_tensor.shape}, Query: {q_tensor.shape}", file=sys.stderr) # Optional
        return []
    sims = (embeds_tensor @ q_tensor).cpu().numpy()
    actual_k = min(k, len(sims))
    if actual_k == 0: return []
    top_indices = sims.argsort()[-actual_k:][::-1]
    results, current_tokens = [], 0
    for hit_idx in top_indices:
        chunk_meta = meta_list[hit_idx]
        snippet_text = chunk_meta["source_code"]
        token_count = len(snippet_text.split())
        if current_tokens + token_count > max_tokens and len(results) > 0:
            if k == 1 and not results: pass # Allow first if k=1
            else: continue
        results.append({
            "file": chunk_meta["file_path"], "lines": f"{chunk_meta['start_line']}-{chunk_meta['end_line']}",
            "snippet": snippet_text, "element_name": chunk_meta["element_name"],
            "element_type": chunk_meta["element_type"], "docstring": chunk_meta["docstring"]
        })
        current_tokens += token_count
        if len(results) >= k: break
    return results

def _handle_build_cli(args: argparse.Namespace):
    # print("Info: CLI: Initiating index build...", file=sys.stderr) # Optional
    build_index(repo_root_path=args.repo, index_output_path=args.index, model_name=args.model)

def _handle_query_cli(args: argparse.Namespace):
    # print(f"Info: CLI: Querying index '{args.index}' with query: '{args.query}'", file=sys.stderr) # Optional
    try:
        results = get_code_context(query=args.query, index_file_path=args.index, k=args.k,
                                   max_tokens=args.max_tokens, query_model_name=args.model)
        if results:
            print("=== Query Results ===") # This is the main output for user
            for res_idx, res in enumerate(results):
                print(f"\n--- Result {res_idx+1} ---")
                print(f"File: {res['file']}")
                print(f"Element: {res['element_name']} ({res['element_type']})")
                print(f"Lines: {res['lines']}")
                if res.get('docstring'): print(f"Docstring: {res['docstring'][:200]}{'...' if len(res['docstring']) > 200 else ''}")
                print(f"Snippet:\n{res['snippet']}")
        else:
            print("No relevant snippets found.")
    except FileNotFoundError as e: print(f"Error: {e}. Ensure index file exists.", file=sys.stderr)
    except Exception as e: print(f"An error occurred during query: {e}", file=sys.stderr)

def _cli_main(argv=None):
    if argv is None: argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description="Build or query AST-based dense code index.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", help="Sub-command to execute", required=True if argv else False)
    # Build
    p_build = subparsers.add_parser("build", help="Build dense code index.")
    p_build.add_argument("--repo", type=str, required=True, help="Path to code repository root.")
    p_build.add_argument("--index", type=str, required=True, help="Path to save output .npz index file.")
    p_build.add_argument("--model", type=str, default=DEFAULT_MODEL, help="SentenceTransformer model name.")
    p_build.set_defaults(func=_handle_build_cli)
    # Query
    p_query = subparsers.add_parser("query", help="Query dense code index.")
    p_query.add_argument("--index", type=str, required=True, help="Path to .npz index file.")
    p_query.add_argument("--query", type=str, required=True, help="Natural language query string.")
    p_query.add_argument("--k", type=int, default=3, help="Number of top results.")
    p_query.add_argument("--max_tokens", type=int, default=2000, help="Max total tokens for snippets.")
    p_query.add_argument("--model", type=str, default=DEFAULT_MODEL, help="SentenceTransformer model for query.")
    p_query.set_defaults(func=_handle_query_cli)

    if not argv: parser.print_help(sys.stderr); sys.exit(1)
    args = parser.parse_args(argv)
    args.func(args)

if __name__ == "__main__":
    _cli_main()