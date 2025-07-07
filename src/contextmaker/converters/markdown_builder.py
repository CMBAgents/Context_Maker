#!/usr/bin/env python
"""
This script builds Sphinx documentation in Markdown format and combines it into a single file
for use as context with Large Language Models (LLMs).
"""

import argparse
import glob
import logging
import os
import shutil
import subprocess
import tempfile
import html2text
import re
import pkgutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def create_safe_conf_py(original_conf_path):
    """
    Create a safe version of conf.py by removing problematic sys.exit() calls.
    
    Args:
        original_conf_path (str): Path to the original conf.py file
        
    Returns:
        str: Path to the temporary safe conf.py file, or None if failed
    """
    try:
        with open(original_conf_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if the file contains sys.exit() calls
        if 'sys.exit(' in content:
            logger.warning(" 📄 Detected sys.exit() calls in conf.py, creating a safe version...")
            
            # Create a temporary directory for the safe conf.py
            temp_dir = tempfile.mkdtemp(prefix="safe_conf_")
            safe_conf_path = os.path.join(temp_dir, "conf.py")
            
            # Remove or comment out sys.exit() calls
            # This regex matches sys.exit() calls and comments them out
            safe_content = re.sub(r'sys\.exit\([^)]*\)', '# sys.exit() - patched by contextmaker', content)
            
            with open(safe_conf_path, 'w', encoding='utf-8') as f:
                f.write(safe_content)
            
            logger.info(f" 📄 Created safe conf.py at: {safe_conf_path}")
            return safe_conf_path
        else:
            return original_conf_path
            
    except Exception as e:
        logger.error(f" 📄 Failed to create safe conf.py: {e}")
        return original_conf_path


def create_minimal_conf_py(sphinx_source, source_root):
    """
    Create a minimal working conf.py when the original one is problematic.
    Args:
        sphinx_source (str): Path to the Sphinx source directory
        source_root (str): Path to the source code root
    Returns:
        str: Path to the minimal conf.py file
    """
    # Detect all top-level modules in source_root
    autodoc_mock_imports = set()
    for importer, modname, ispkg in pkgutil.iter_modules([source_root]):
        autodoc_mock_imports.add(modname)
    # Also add submodules (one level deep)
    for importer, modname, ispkg in pkgutil.walk_packages([source_root]):
        autodoc_mock_imports.add(modname.split('.')[0])
    temp_dir = tempfile.mkdtemp(prefix="minimal_conf_")
    minimal_conf_path = os.path.join(temp_dir, "conf.py")
    minimal_conf_content = f'''# Minimal Sphinx configuration created by contextmaker
import os
import sys
sys.path.insert(0, r'{source_root}')
project = 'Library Documentation'
copyright = '2025'
author = 'ContextMaker'
release = '1.0.0'
version = '1.0.0'
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
html_theme = 'alabaster'
autodoc_mock_imports = {sorted(list(autodoc_mock_imports))}
intersphinx_mapping = {{
    'python': ('https://docs.python.org/3/', None),
}}
'''
    with open(minimal_conf_path, 'w', encoding='utf-8') as f:
        f.write(minimal_conf_content)
    logger.info(f" 📄 Created minimal conf.py at: {minimal_conf_path}")
    return minimal_conf_path


def parse_args():
    parser = argparse.ArgumentParser(description="Build Sphinx documentation in Markdown format for LLM context.")
    parser.add_argument("--exclude", type=str, default="", help="Comma-separated list of files to exclude (without .md extension)")
    parser.add_argument("--output", type=str, required=True, help="Output file path")
    parser.add_argument("--sphinx-source", type=str, required=True, help="Path to Sphinx source directory (where conf.py and index.rst are)")
    parser.add_argument("--conf", type=str, default=None, help="Path to conf.py (default: <sphinx-source>/conf.py)")
    parser.add_argument("--index", type=str, default=None, help="Path to index.rst (default: <sphinx-source>/index.rst)")
    parser.add_argument("--notebook", type=str, default=None, help="Path to notebook to convert and append")
    parser.add_argument("--source-root", type=str, required=True, help="Absolute path to the root of the source code to add to sys.path for Sphinx autodoc.")
    parser.add_argument("--library-name", type=str, default=None, help="Name of the library for the documentation title.")
    parser.add_argument("--html-to-text", action="store_true", help="Build Sphinx HTML and convert to text instead of Markdown.")
    return parser.parse_args()


def patch_sys_exit_in_py_files(root_dir):
    """
    Parcourt tous les fichiers .py sous root_dir et commente les appels à sys.exit().
    """
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.py'):
                file_path = os.path.join(dirpath, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if 'sys.exit(' in content:
                        patched = re.sub(r'sys\.exit\([^)]*\)', '# sys.exit() - patched by contextmaker', content)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(patched)
                        logger.info(f" 📄 Patched sys.exit() in {file_path}")
                except Exception as e:
                    logger.warning(f" 📄 Could not patch {file_path}: {e}")


def copy_and_patch_source(original_path):
    """
    Copie le dossier original_path dans un dossier temporaire et patch tous les .py pour neutraliser sys.exit().
    Retourne le chemin du dossier temporaire.
    """
    temp_dir = tempfile.mkdtemp(prefix="patched_src_")
    dest_path = os.path.join(temp_dir, os.path.basename(original_path))
    if os.path.isdir(original_path):
        shutil.copytree(original_path, dest_path, dirs_exist_ok=True)
    else:
        shutil.copy2(original_path, dest_path)
    patch_sys_exit_in_py_files(dest_path)
    return dest_path


def build_markdown(sphinx_source, conf_path, source_root, robust=False):
    # Copie et patch du dossier source_root et sphinx_source
    patched_source_root = copy_and_patch_source(source_root)
    patched_sphinx_source = copy_and_patch_source(sphinx_source)
    # On utilise le conf.py du dossier patché
    patched_conf_path = os.path.join(patched_sphinx_source, os.path.basename(conf_path))
    build_dir = tempfile.mkdtemp(prefix="sphinx_build_")
    logger.info(f" 📄 Temporary build directory: {build_dir}")
    os.makedirs(build_dir, exist_ok=True)
    if robust:
        # Always use minimal conf.py
        minimal_conf_path = create_minimal_conf_py(patched_sphinx_source, patched_source_root)
        conf_dir = os.path.dirname(minimal_conf_path)
        logger.info(f" 📄 Forcing minimal conf.py for robust mode: {minimal_conf_path}")
        result = subprocess.run(
            ["sphinx-build", "-b", "markdown", "-c", conf_dir, patched_sphinx_source, build_dir],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": patched_source_root + os.pathsep + os.environ.get("PYTHONPATH", "")}
        )
        if result.returncode != 0:
            logger.error(" 📄 sphinx-build failed even with minimal configuration in robust mode.")
            logger.error(" 📄 stdout:\n%s", result.stdout)
            logger.error(" 📄 stderr:\n%s", result.stderr)
    else:
        # Crée une version safe du conf.py si besoin
        safe_conf_path = create_safe_conf_py(patched_conf_path)
        conf_dir = os.path.dirname(safe_conf_path)
        logger.info(f" 📄 sphinx_source: {patched_sphinx_source}")
        logger.info(f" 📄 conf_path: {safe_conf_path}")
        logger.info(f" 📄 build_dir: {build_dir}")
        logger.info(f" 📄 sphinx-build command: sphinx-build -b markdown -c {conf_dir} {patched_sphinx_source} {build_dir}")
        logger.info(" 📄 Running sphinx-build...")
        result = subprocess.run(
            ["sphinx-build", "-b", "markdown", "-c", conf_dir, patched_sphinx_source, build_dir],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": patched_source_root + os.pathsep + os.environ.get("PYTHONPATH", "")}
        )
        if result.returncode != 0:
            logger.error(" 📄 sphinx-build failed with return code %s", result.returncode)
            logger.error(" 📄 stdout:\n%s", result.stdout)
            logger.error(" 📄 stderr:\n%s", result.stderr)
            # Try with minimal conf.py
            minimal_conf_path = create_minimal_conf_py(patched_sphinx_source, patched_source_root)
            conf_dir = os.path.dirname(minimal_conf_path)
            result = subprocess.run(
                ["sphinx-build", "-b", "markdown", "-c", conf_dir, patched_sphinx_source, build_dir],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": patched_source_root + os.pathsep + os.environ.get("PYTHONPATH", "")}
            )
            if result.returncode == 0:
                logger.info(" ✅ sphinx-build completed successfully with minimal configuration.")
                try:
                    temp_dir = os.path.dirname(minimal_conf_path)
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f" 📄 Failed to clean up minimal conf.py: {e}")
            else:
                logger.error(" 📄 sphinx-build failed even with minimal configuration.")
                logger.error(" 📄 stdout:\n%s", result.stdout)
                logger.error(" 📄 stderr:\n%s", result.stderr)
                try:
                    temp_dir = os.path.dirname(minimal_conf_path)
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f" 📄 Failed to clean up minimal conf.py: {e}")
    # Nettoyage des dossiers temporaires
    for temp in [patched_source_root, patched_sphinx_source]:
        try:
            shutil.rmtree(temp)
        except Exception:
            pass
    return build_dir


def extract_toctree_order_recursive(rst_path, seen=None):
    """
    Recursively extract the order of documents from .. toctree:: directives in rst files.
    Args:
        rst_path (str): Path to the rst file to parse.
        seen (set): Set of already seen rst file basenames (without extension) to avoid cycles.
    Returns:
        list: Ordered list of rst file basenames (without extension).
    """
    if seen is None:
        seen = set()
    try:
        with open(rst_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logger.error(f" 📄  Could not read {rst_path}: {e}")
        return []

    toctree_docs = []
    in_toctree = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(".. toctree::"):
            in_toctree = True
            continue
        if in_toctree:
            if stripped == "" or stripped.startswith(":"):
                continue
            if stripped.startswith(".. "):  # another directive
                break
            doc = stripped
            if doc not in seen:
                seen.add(doc)
                toctree_docs.append(doc)
    # Recursively process referenced rst files
    result = []
    rst_dir = os.path.dirname(rst_path)
    for doc in toctree_docs:
        result.append(doc)
        doc_path = os.path.join(rst_dir, doc + ".rst")
        if os.path.exists(doc_path):
            subdocs = extract_toctree_order_recursive(doc_path, seen)
            for subdoc in subdocs:
                if subdoc not in result:
                    result.append(subdoc)
    return result


def combine_markdown(build_dir, exclude, output, index_path, library_name):
    md_files = glob.glob(os.path.join(build_dir, "*.md"))
    logger.info(f"[DEBUG] Found .md files in build_dir: {[os.path.basename(f) for f in md_files]}")
    exclude_set = set(f"{e.strip()}.md" for e in exclude if e.strip())

    filtered = [f for f in md_files if os.path.basename(f) not in exclude_set]

    index_md = None
    others = []
    for f in filtered:
        if os.path.basename(f).lower() == "index.md":
            index_md = f
        else:
            others.append(f)

    # Use recursive toctree extraction
    toctree_order = extract_toctree_order_recursive(index_path) if index_path else []
    logger.info(f"[DEBUG] Toctree order (from .rst): {toctree_order}")
    name_to_file = {os.path.splitext(os.path.basename(f))[0]: f for f in others}
    ordered = []
    for doc in toctree_order:
        if doc in name_to_file:
            logger.info(f"[DEBUG] Including referenced file: {doc}.md")
            ordered.append(name_to_file.pop(doc))
        else:
            logger.warning(f"[DEBUG] Referenced in toctree but .md not found: {doc}.md")

    remaining = sorted(name_to_file.values())
    if remaining:
        logger.info(f"[DEBUG] .md files not referenced in toctree: {[os.path.basename(f) for f in remaining]}")
    ordered.extend(remaining)

    final_order = ([index_md] if index_md else []) + ordered

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as out:
        out.write(f"# - {library_name} | Complete Documentation -\n\n")
        for i, f in enumerate(final_order):
            if i > 0:
                out.write("\n\n---\n\n")
            section = os.path.splitext(os.path.basename(f))[0]
            out.write(f"## {section}\n\n")
            with open(f, encoding="utf-8") as infile:
                out.write(infile.read())
                out.write("\n\n")

    logger.info(f" 📄 Combined markdown written to {output}")


def convert_notebook(nb_path):
    if not shutil.which("jupytext"):
        logger.error(" 📄 jupytext is required to convert notebooks.")
        return None

    md_path = os.path.splitext(nb_path)[0] + ".md"
    cmd = ["jupytext", "--to", "md", "--opt", "notebook_metadata_filter=-all", nb_path]
    logger.info(f" 📄 Converting notebook {nb_path} to markdown...")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f" 📄 Failed to convert notebook:\n{result.stderr}")
        return None
    if not os.path.exists(md_path):
        logger.error(f" 📄 Expected markdown file {md_path} not found after conversion.")
        return None

    logger.info(f" ✅ Notebook converted to {md_path}")
    return md_path


def append_notebook_markdown(output_file, notebook_md):
    with open(output_file, "a", encoding="utf-8") as out, open(notebook_md, encoding="utf-8") as nb_md:
        out.write("\n\n# Notebook\n\n---\n\n")
        out.write(nb_md.read())
    logger.info(f" 📄 Appended notebook markdown from {notebook_md} to {output_file}")


def build_html_and_convert_to_text(sphinx_source, conf_path, source_root, output):
    # Copie et patch du dossier source_root et sphinx_source
    patched_source_root = copy_and_patch_source(source_root)
    patched_sphinx_source = copy_and_patch_source(sphinx_source)
    # On utilise le conf.py du dossier patché
    patched_conf_path = os.path.join(patched_sphinx_source, os.path.basename(conf_path))
    build_dir = tempfile.mkdtemp(prefix="sphinx_html_build_")
    logger.info(f" 📄 Temporary HTML build directory: {build_dir}")
    os.makedirs(build_dir, exist_ok=True)
    # Crée une version safe du conf.py si besoin
    safe_conf_path = create_safe_conf_py(patched_conf_path)
    conf_dir = os.path.dirname(safe_conf_path)
    logger.info(f" 📄 sphinx_source: {patched_sphinx_source}")
    logger.info(f" 📄 conf_path: {safe_conf_path}")
    logger.info(f" 📄 build_dir: {build_dir}")
    logger.info(f" 📄 sphinx-build command: sphinx-build -b html -c {conf_dir} {patched_sphinx_source} {build_dir}")
    logger.info(" 📄 Running sphinx-build (HTML)...")
    result = subprocess.run(
        ["sphinx-build", "-b", "html", "-c", conf_dir, patched_sphinx_source, build_dir],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": patched_source_root + os.pathsep + os.environ.get("PYTHONPATH", "")}
    )
    if result.returncode != 0:
        logger.error(" 📄 sphinx-build (HTML) failed with return code %s", result.returncode)
        logger.error(" 📄 stdout:\n%s", result.stdout)
        logger.error(" 📄 stderr:\n%s", result.stderr)
        
        # Check for common error patterns and provide helpful messages
        stderr_lower = result.stderr.lower()
        if "sys.exit()" in result.stderr:
            logger.error(" 📄 The library's conf.py file contains sys.exit() calls, which prevents Sphinx from building.")
            logger.error(" 📄 This is a common issue with some libraries. The library may need to be properly installed or have its dependencies resolved.")
            logger.error(" 📄 Try installing the library and its dependencies first, or use a different documentation source.")
        elif "circular import" in stderr_lower or "partially initialized module" in stderr_lower:
            logger.error(" 📄 This appears to be a circular import issue. This is common with complex libraries like numpy.")
            logger.error(" 📄 The library may need to be properly installed or the documentation may have dependency issues.")
        elif "import error" in stderr_lower:
            logger.error(" 📄 Import error detected. The library may have missing dependencies for documentation building.")
        elif "configuration error" in stderr_lower:
            logger.error(" 📄 Configuration error detected. The library's Sphinx configuration may be incompatible.")
            logger.error(" 📄 This could be due to missing dependencies, incompatible extensions, or configuration issues.")
            logger.error(" 📄 Trying with minimal configuration...")
            
            # Try with minimal conf.py
            minimal_conf_path = create_minimal_conf_py(patched_sphinx_source, patched_source_root)
            conf_dir = os.path.dirname(minimal_conf_path)
            
            result = subprocess.run(
                ["sphinx-build", "-b", "html", "-c", conf_dir, patched_sphinx_source, build_dir],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": patched_source_root + os.pathsep + os.environ.get("PYTHONPATH", "")}
            )
            
            if result.returncode == 0:
                logger.info(" ✅ sphinx-build completed successfully with minimal configuration.")
                # Clean up minimal conf.py
                try:
                    temp_dir = os.path.dirname(minimal_conf_path)
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f" 📄 Failed to clean up minimal conf.py: {e}")
            else:
                logger.error(" 📄 sphinx-build failed even with minimal configuration.")
                logger.error(" 📄 stdout:\n%s", result.stdout)
                logger.error(" 📄 stderr:\n%s", result.stderr)
                # Clean up minimal conf.py
                try:
                    temp_dir = os.path.dirname(minimal_conf_path)
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f" 📄 Failed to clean up minimal conf.py: {e}")
                return False
    else:
        logger.info(" ✅ sphinx-build (HTML) completed successfully.")

    logger.info(" 📄 Files in build_dir after sphinx-build (HTML): %s", os.listdir(build_dir))

    # Nettoyage des dossiers temporaires
    for temp in [patched_source_root, patched_sphinx_source, os.path.dirname(safe_conf_path)]:
        try:
            shutil.rmtree(temp)
        except Exception:
            pass

    # Convert all HTML files to text and concatenate
    html_files = sorted(glob.glob(os.path.join(build_dir, "*.html")))
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output), exist_ok=True)
    
    # Extract library name from output path
    library_name = os.path.splitext(os.path.basename(output))[0]
    
    with open(output, "w", encoding="utf-8") as out:
        out.write(f"# - Complete Documentation | {library_name} -\n\n")
        for html_file in html_files:
            section = os.path.splitext(os.path.basename(html_file))[0]
            out.write(f"## {section}\n\n")
            with open(html_file, "r", encoding="utf-8") as f:
                html = f.read()
            text = html2text.html2text(html)
            out.write(text)
            out.write("\n\n---\n\n")
    logger.info(f" 📄 Combined HTML-to-text written to {output}")
    return True


def find_notebooks_in_doc_dirs():
    """
    Find all .ipynb files in 'docs/', 'doc/', and 'docs/source/' directories, sorted alphabetically.
    Returns a list of absolute paths.
    """
    candidates = []
    for doc_dir in ["docs", "doc", "docs/source"]:
        if os.path.isdir(doc_dir):
            candidates.extend(glob.glob(os.path.join(doc_dir, "*.ipynb")))
    return sorted([os.path.abspath(nb) for nb in candidates])


def main():
    args = parse_args()
    exclude = args.exclude.split(",") if args.exclude else []
    sphinx_source = os.path.abspath(args.sphinx_source)
    conf_path = os.path.abspath(args.conf) if args.conf else os.path.join(sphinx_source, "conf.py")
    index_path = os.path.abspath(args.index) if args.index else os.path.join(sphinx_source, "index.rst")
    source_root = os.path.abspath(args.source_root)
    library_name = args.library_name if args.library_name else os.path.basename(source_root)
    # Nouveau mode : HTML -> texte
    if hasattr(args, 'html_to_text') and args.html_to_text:
        build_html_and_convert_to_text(sphinx_source, conf_path, source_root, args.output)
        logger.info(" ✅ Sphinx HTML to text conversion successful.")
        return
    # Always use robust mode by default
    build_dir = build_markdown(sphinx_source, conf_path, source_root, robust=True)
    combine_markdown(build_dir, exclude, args.output, index_path, library_name)
    # Append all notebooks found in docs/ and doc/ (alphabetically)
    appended_notebooks = set()
    for nb_path in find_notebooks_in_doc_dirs():
        notebook_md = convert_notebook(nb_path)
        if notebook_md:
            append_notebook_markdown(args.output, notebook_md)
            appended_notebooks.add(os.path.abspath(nb_path))
    # Still allow --notebook, but avoid duplicate if already appended
    if args.notebook:
        nb_abs = os.path.abspath(args.notebook)
        if nb_abs not in appended_notebooks:
            notebook_md = convert_notebook(args.notebook)
            if notebook_md:
                append_notebook_markdown(args.output, notebook_md)
    logger.info(" ✅ Sphinx to Markdown conversion successful.")


if __name__ == "__main__":
    main()