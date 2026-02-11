"""Sphinx configuration for the python-spot documentation."""

from __future__ import annotations

import os
import sys
from datetime import datetime

# Ensure the package can be imported when building the docs.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

project = "python-spot"
author = "srichs"
current_year = datetime.now().year
copyright = f"{current_year}, {author}"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
]

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

autodoc_typehints = "description"

templates_path = ["_templates"]
exclude_patterns: list[str] = ["_build"]

html_static_path = ["_static"]
# html_theme = "alabaster"
html_theme = "furo"
