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
import nbformat
import json
import itertools

import numpy as np
import torch

try:
    from context_store_json import export_ast_chunks_to_json, query_json_context
except ImportError:
    pass 
# sentence_transformers is imported only within functions that use it.

# ---------------------------------------------------------------------
DEFAULT_MODEL = "intfloat/e5-base-v2"

_CACHED_INDICES = {}
_CACHED_MODELS = {}
# ---------------------------------------------------------------------

def _get_ast_node_source_segment(source_lines, node):
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

def _extract_ast_chunks_from_file(py_file_path, repo_root_path):
    try:
        file_content = py_file_path.read_text(encoding="utf-8", errors="ignore")
        source_lines = file_content.splitlines(True)
        tree = ast.parse(file_content, filename=str(py_file_path))
    except Exception as e:
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

def _get_sentence_transformer_model(model_name):
    if model_name not in _CACHED_MODELS:
        from sentence_transformers import SentenceTransformer
        print(f"Info: Loading SentenceTransformer model: {model_name}...", file=sys.stderr)
        _CACHED_MODELS[model_name] = SentenceTransformer(model_name, device="cpu")
        print(f"Info: Model {model_name} loaded.", file=sys.stderr)
    return _CACHED_MODELS[model_name]

def _embed_texts_batch(texts, model_name, is_query=False):
    if not texts: return np.array([])
    texts_to_embed = [f"query: {text}" for text in texts] if is_query else texts
    show_progress = not is_query
    model = _get_sentence_transformer_model(model_name)
    return model.encode(texts_to_embed, batch_size=32 if not is_query else 1,
                        show_progress_bar=show_progress, normalize_embeddings=True)

def build_index(repo_root_path, index_output_path, model_name=DEFAULT_MODEL):
    repo_root, index_file = Path(repo_root_path).resolve(), Path(index_output_path).resolve()
    if not repo_root.is_dir(): raise FileNotFoundError(f"Repo root not found: {repo_root}")
    all_src_texts, all_meta = [], []
    print(f"Info: Scanning Python files in: {repo_root} for AST chunking...", file=sys.stderr)
    py_files = [p for p in repo_root.rglob("*.py") if not any(ex in p.parts for ex in
                ['.git', '.vscode', '.idea', '__pycache__', 'node_modules', 'build', 'dist',
                 'venv', 'env', '.env', 'site-packages', '.ipynb_checkpoints', 'tests', 'test', 'docs/_build'])]
    print(f"Info: Found {len(py_files)} Python files to process.", file=sys.stderr)
    for py_path in py_files:
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

def _load_index_from_file(index_file_path):
    data = np.load(index_file_path, allow_pickle=True)
    embeds_np, meta_np = data.get("embeddings"), data.get("meta")
    if embeds_np is None or meta_np is None: raise ValueError(f"Index missing 'embeddings' or 'meta': {index_file_path}")
    meta_list = [dict(item) for item in meta_np]
    return torch.tensor(embeds_np, dtype=torch.float32), meta_list

def get_code_context(query, index_file_path, k=3, max_tokens=2000, query_model_name=DEFAULT_MODEL):
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
            if k == 1 and not results: pass
            else: continue
        results.append({
            "file": chunk_meta["file_path"], "lines": f"{chunk_meta['start_line']}-{chunk_meta['end_line']}",
            "snippet": snippet_text, "element_name": chunk_meta["element_name"],
            "element_type": chunk_meta["element_type"], "docstring": chunk_meta["docstring"]
        })
        current_tokens += token_count
        if len(results) >= k: break
    return results

def _handle_build_cli(args):
    build_index(repo_root_path=args.repo, index_output_path=args.index, model_name=args.model)

def _handle_query_cli(args):
    try:
        results = get_code_context(query=args.query, index_file_path=args.index, k=args.k,
                                   max_tokens=args.max_tokens, query_model_name=args.model)
        if results:
            print("=== Query Results ===")
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

def process_source(path, text, elem_type, chunks, meta, repo):
    lines = text.splitlines(True) 
    if not lines:
        return

    active_headings_stack = []
    discovered_headings_info = []

    for i, line_content in enumerate(lines):
        stripped_line = line_content.lstrip()
        if stripped_line.startswith("#"):
            heading_level = len(stripped_line) - len(stripped_line.lstrip("#"))
            heading_title = stripped_line[heading_level:].strip()

            while active_headings_stack and active_headings_stack[-1][0] >= heading_level:
                active_headings_stack.pop()
            
            active_headings_stack.append((heading_level, heading_title))
            discovered_headings_info.append((i, heading_level, list(active_headings_stack)))

    discovered_headings_info.append((len(lines), 0, [])) 

    for idx in range(len(discovered_headings_info) - 1):
        current_heading_start_line_idx, _, current_heading_path_list = discovered_headings_info[idx]
        next_heading_start_line_idx, _, _ = discovered_headings_info[idx+1]
        
        snippet_lines = lines[current_heading_start_line_idx : next_heading_start_line_idx]

        non_empty_lines_count = sum(1 for l in snippet_lines if l.strip())
        if non_empty_lines_count < 5:
            continue
        
        snippet_text = ''.join(snippet_lines)
        heading_path_str = " > ".join(h_title for _, h_title in current_heading_path_list)

        meta.append({
            "file_path": str(path.relative_to(repo)),
            "heading_path": heading_path_str,
            "element_type": elem_type,
            "start_line": current_heading_start_line_idx + 1,
            "end_line": next_heading_start_line_idx,
        })
        chunks.append(snippet_text)

def build_prose_index(repo_root_path, index_output_path, model_name=DEFAULT_MODEL):
    repo_root_path = Path(repo_root_path).resolve()
    index_output_path = Path(index_output_path)

    all_chunks_text = []
    all_chunks_meta = []

    prose_extensions = {".md", ".txt", ".rst"}
    notebook_extensions = {".ipynb"}

    EXCLUDE_DIR_NAMES_EXACT = {
        '.ipynb_checkpoints', 'build', 'dist', '__pycache__', 
        'venv', 'node_modules'
    }

    for file_path in repo_root_path.rglob("*"):
        should_skip = False
        try:
            relative_parent_dirs = file_path.relative_to(repo_root_path).parts[:-1]
            for part_name in relative_parent_dirs:
                if part_name.startswith('.') or part_name in EXCLUDE_DIR_NAMES_EXACT:
                    should_skip = True
                    break
        except ValueError:
            should_skip = True
        
        if should_skip:
            continue

        if not file_path.is_file():
            continue

        if file_path.suffix in prose_extensions:
            try:
                text_content = file_path.read_text(encoding="utf-8")
                elem_type = "Markdown" if file_path.suffix == ".md" else "ProseText"
                process_source(file_path, text_content, elem_type, 
                               all_chunks_text, all_chunks_meta, repo_root_path)
            except Exception as e:
                print(f"Error processing prose file {file_path}: {e}", file=sys.stderr)

        elif file_path.suffix in notebook_extensions:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)

                markdown_cell_sources = []
                for cell in notebook.cells:
                    if "ignore" in cell.metadata.get("tags", []):
                        continue

                    if cell.cell_type == "markdown":
                        markdown_cell_sources.append(cell.source)
                    elif cell.cell_type == "code":
                        cell_source_stripped = cell.source.strip()
                        if cell_source_stripped.startswith(("!", "%")):
                            continue
                
                if markdown_cell_sources:
                    concatenated_markdown_content = "\n\n".join(markdown_cell_sources)
                    process_source(file_path, concatenated_markdown_content, "Notebook",
                                   all_chunks_text, all_chunks_meta, repo_root_path)
            except Exception as e:
                print(f"Error processing notebook {file_path}: {e}", file=sys.stderr)
    
    if not all_chunks_text:
        print(f"No text chunks found in {repo_root_path} after exclusions. Prose index will not be built.", file=sys.stderr)
        return

    try:
        embeddings_array = _embed_texts_batch(all_chunks_text, model_name, is_query=False) 

        index_output_path.parent.mkdir(parents=True, exist_ok=True)
        
        np.savez_compressed(
            index_output_path,
            embeddings=embeddings_array,
            texts=np.array(all_chunks_text, dtype=object), 
            metadata=all_chunks_meta 
        )
        print(f"Prose index built with {len(all_chunks_text)} chunks and saved to {index_output_path}", file=sys.stderr)

    except Exception as e:
        print(f"Failed to build or save prose index for {repo_root_path}: {e}", file=sys.stderr)

def get_prose_context(query, index_file_path, k=3, model_name=DEFAULT_MODEL):
    try:
        data = np.load(str(index_file_path), allow_pickle=True)
        embeddings = data["embeddings"]
        texts = data["texts"]
        meta = list(data["metadata"])
    except FileNotFoundError:
        print(f"Error: Index file not found at {index_file_path}", file=sys.stderr)
        return []
    except KeyError as e:
        print(f"Error: Index file {index_file_path} is missing expected field: {e}", file=sys.stderr)
        return []

    if embeddings.size == 0 or len(texts) == 0:
        print(f"Warning: Index {index_file_path} contains no data.", file=sys.stderr)
        return []
        
    query_embedding = _embed_texts_batch([query], model_name, is_query=True)
    if query_embedding.ndim > 1:
        query_embedding = query_embedding[0]

    q_norm = np.linalg.norm(query_embedding)
    e_norm = np.linalg.norm(embeddings, axis=1)

    if q_norm == 0:
        similarities = np.zeros(embeddings.shape[0])
    else:
        valid_e_norm_mask = e_norm > 0
        similarities = np.zeros(embeddings.shape[0])
        if np.any(valid_e_norm_mask):
            dot_product = np.dot(embeddings[valid_e_norm_mask], query_embedding)
            similarities[valid_e_norm_mask] = dot_product / (e_norm[valid_e_norm_mask] * q_norm)
        
    num_items = len(similarities)
    actual_k = min(k, num_items)
    if actual_k == 0 and num_items > 0:
        return []
    elif num_items == 0:
        return []

    ids = np.argsort(similarities)[::-1][:actual_k].astype(int)

    results = []
    for i in ids:
        m = meta[i]
        results.append({
            "file": m["file_path"],
            "heading_path": m["heading_path"],
            "element_type": m["element_type"],
            "lines": f"{m['start_line']}-{m['end_line']}",
            "snippet": texts[i],
        })
    return results

def _cli_main(argv=None):
    if argv is None: argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description="Build or query AST-based dense code index.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", help="Sub-command to execute", required=True if argv else False)
    
    _json_build = subparsers.add_parser("build-json",
                                        help="Export AST chunks to JSON context files")
    _json_build.add_argument("--repo", required=True,
                             help="Path to repository root")
    _json_build.add_argument("--output-base-name", required=True,
                             help="Base name for output JSON files")
    _json_build.set_defaults(
        func=lambda a: export_ast_chunks_to_json(a.repo, a.output_base_name))
    
    _json_query = subparsers.add_parser("query-json",
                                        help="Query a JSON context store")
    _json_query.add_argument("--signatures-file", required=True,
                             help="Path to signatures JSON")
    _json_query.add_argument("--source-file", required=True,
                             help="Path to fullsource JSON")
    _json_query.add_argument("--query", required=True,
                             help="Search query string")
    _json_query.add_argument("--k", type=int, default=3,
                             help="Number of results to return")
    _json_query.set_defaults(
        func=lambda a: print(json.dumps(
            query_json_context(a.query,
                               a.signatures_file,
                               a.source_file,
                               a.k),
            ensure_ascii=False, indent=2)))

    _pb = subparsers.add_parser("build-prose", help="Build prose embedding index")
    _pb.add_argument("--repo", required=True, help="Path to repo root")
    _pb.add_argument("--output", required=True, help="Output base path for prose index")
    _pb.add_argument("--model", default=DEFAULT_MODEL, help="Embedding model name")
    _pb.set_defaults(func=lambda args: build_prose_index(args.repo, args.output, args.model))

    _pq = subparsers.add_parser("query-prose", help="Query prose embedding index")
    _pq.add_argument("--index", required=True, help="Path to prose index (.npz)")
    _pq.add_argument("--query", required=True, help="Query text")
    _pq.add_argument("--k", type=int, default=3, help="Number of results")
    _pq.add_argument("--model", default=DEFAULT_MODEL, help="Embedding model name")
    _pq.set_defaults(func=lambda args: print(
        json.dumps(
            get_prose_context(
                query=args.query,
                index_file_path=args.index,
                k=args.k,
                model_name=args.model
            ),
            ensure_ascii=False, indent=2
        )
    ))
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
    p_query.add_argument("--model", type=str, default=DEFAULT_MODEL, help="SentenceTransformer model for query.")
    p_query.set_defaults(func=_handle_query_cli)

    if not argv: parser.print_help(sys.stderr); sys.exit(1)
    args = parser.parse_args(argv)
    args.func(args)

if __name__ == "__main__":
    _cli_main()
