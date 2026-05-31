from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _clean_label(value: str | int) -> str:
    """Return a BIDS label without the entity prefix."""
    text = str(value).strip()
    for prefix in ("sub-", "ses-", "task-", "run-"):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


@dataclass(frozen=True)
class BIDSPath:
    """Shared BIDS-style path builder for imaging-linked v2 runs."""

    project_root_pc2: Path
    project_root_pc1: str
    sub: str
    ses: str | int
    task: str
    run: str | int

    @property
    def sub_label(self) -> str:
        return _clean_label(self.sub)

    @property
    def ses_label(self) -> str:
        return _clean_label(self.ses)

    @property
    def task_label(self) -> str:
        return _clean_label(self.task)

    @property
    def run_label(self) -> str:
        return _clean_label(self.run)

    @property
    def func_dir_pc2(self) -> Path:
        return self.project_root_pc2 / f"sub-{self.sub_label}" / f"ses-{self.ses_label}" / "func"

    @property
    def func_dir_pc1(self) -> str:
        root = self.project_root_pc1.rstrip("/\\")
        return f"{root}/sub-{self.sub_label}/ses-{self.ses_label}/func"

    @property
    def stem(self) -> str:
        return f"sub-{self.sub_label}_ses-{self.ses_label}_task-{self.task_label}_run-{self.run_label}"

    def makedirs(self) -> None:
        self.func_dir_pc2.mkdir(parents=True, exist_ok=True)

    def filename(self, suffix: str) -> str:
        suffix = suffix.strip("_")
        if not suffix:
            return f"{self.stem}_"
        return f"{self.stem}_{suffix}"

    def filepath_pc2(self, suffix: str, ext: str) -> Path:
        ext = ext if ext.startswith(".") else f".{ext}"
        return self.func_dir_pc2 / f"{self.filename(suffix)}{ext}"

    @property
    def events_tsv_pc2(self) -> Path:
        return self.filepath_pc2("events", ".tsv")

    @property
    def config_yaml_pc2(self) -> Path:
        return self.filepath_pc2("config", ".yaml")

    @property
    def clock_sync_yaml_pc2(self) -> Path:
        return self.filepath_pc2("clock_sync", ".yaml")
