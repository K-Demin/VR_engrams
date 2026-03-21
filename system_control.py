# -*- coding: utf-8 -*-
"""Calibration/prototyping snippets (NOT runtime orchestration).

This file is intentionally retained for bench testing examples only.
Runtime experiment logic should use dedicated controllers in `hardware/`
and task pipelines in `main_pipeline.py` / `tasks/`.
"""

if __name__ == "__main__":
    raise SystemExit(
        "system_control.py is calibration/prototyping-only and should not be run "
        "as the runtime orchestrator. Use main_pipeline.py with a task config instead."
    )
