---
name: feedback-use-uv
description: Always use uv to run Python scripts in this project, not python3 directly
metadata:
  type: feedback
---

Always run Python with `uv run python` (or `uv run script.py`), not `python3 ...` directly.

**Why:** The project uses uv for dependency/environment management; running python3 directly may use the wrong interpreter or miss dependencies.

**How to apply:** Replace any `python3 -c ...` or `python3 script.py` with `uv run python -c ...` or `uv run script.py`.
