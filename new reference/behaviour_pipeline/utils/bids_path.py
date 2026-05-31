# -*- coding: utf-8 -*-
"""
utils/bids_path.py
==================
BIDS-inspired path and filename construction for the widefield imaging pipeline.

Adapts the Brain Imaging Data Structure (BIDS) convention to mouse
neuroscience experiments. Human-fMRI BIDS concepts map as follows:

    BIDS concept      → This pipeline
    ─────────────────────────────────
    sub-<label>       → sub-m01, sub-m02, ...  (animal ID)
    ses-<index>       → ses-1, ses-2, ...       (session number, 1 per day in setup)
    task-<label>      → task-puff, task-rest, task-audiolick, ...
    run-<index>       → run-1, run-2, ...       (each script execution = one run)
    <suffix>          → grb, face, body, events (data type)
    <extension>       → .tiff, .avi, .tsv, .yaml

Folder structure
----------------
project/
  sub-m01/
    ses-1/
      func/
        sub-m01_ses-1_task-puff_run-1_body.avi        ← ELP body camera
        sub-m01_ses-1_task-puff_run-1_face.avi        ← face camera (future)
        sub-m01_ses-1_task-puff_run-1_grb.tiff        ← widefield calcium (Andor)
        sub-m01_ses-1_task-puff_run-1_events.tsv      ← behaviour log (PC2)
        sub-m01_ses-1_task-puff_run-1_frames.tsv      ← frame timestamps (PC1)
        sub-m01_ses-1_task-puff_run-1_config.yaml     ← config snapshot

Usage
-----
    from utils.bids_path import BIDSPath

    # Build session paths
    bp = BIDSPath(
        project_root_pc2 = "Y:/my_project",
        project_root_pc1 = "C:/Users/User/Documents/Data/my_project",
        sub              = "m01",
        ses              = 1,
        task             = "puff",
        run              = 1,
    )

    bp.func_dir_pc2          # "Y:/my_project/sub-m01/ses-1/func"
    bp.func_dir_pc1          # "C:/.../func"
    bp.filename("body")      # "sub-m01_ses-1_task-puff_run-1_body"
    bp.filepath_pc2("body", ".avi")  # full path on PC2
    bp.filepath_pc1("body", ".avi")  # full path on PC1

Notes
-----
- ses is a *session number* (integer), not a date. Track the date in your
  experiment spreadsheet. This keeps filenames short and sortable.
- The func/ subfolder is used for all functional data (behaviour + imaging).
  An anat/ subfolder can be added later for anatomical reference images.
- run-1 resets each time you call the pipeline. If you run twice in one session,
  increment the run number via --run argument on the CLI.
"""

import os
from typing import Union


class BIDSPath:
    """
    Constructs BIDS-style paths for both PC1 and PC2.

    Parameters
    ----------
    project_root_pc2 : str
        Root project folder on PC2 (mapped drive, e.g. "Y:/my_project").
    project_root_pc1 : str
        Root project folder on PC1 (local path, e.g. "C:/Users/.../my_project").
    sub : str
        Subject/animal ID without the "sub-" prefix, e.g. "m01".
    ses : int
        Session number (integer, 1-based), e.g. 1.
    task : str
        Task label without "task-" prefix, e.g. "puff", "rest", "audiolick".
    run : int
        Run number (integer, 1-based), e.g. 1.
    """

    def __init__(
        self,
        project_root_pc2: str,
        project_root_pc1: str,
        sub: str,
        ses: int,
        task: str,
        run: int = 1,
    ):
        # Normalise subject: strip any accidental "sub-" prefix
        self.sub  = sub.lower().replace("sub-", "")
        self.ses  = int(ses)
        self.task = task.lower()
        self.run  = int(run)

        self._root_pc2 = project_root_pc2.rstrip("/\\")
        self._root_pc1 = project_root_pc1.rstrip("/\\")

    # ------------------------------------------------------------------
    # BIDS entity labels
    # ------------------------------------------------------------------

    @property
    def sub_label(self) -> str:
        return f"sub-{self.sub}"

    @property
    def ses_label(self) -> str:
        return f"ses-{self.ses}"

    @property
    def task_label(self) -> str:
        return f"task-{self.task}"

    @property
    def run_label(self) -> str:
        return f"run-{self.run}"

    # ------------------------------------------------------------------
    # Directories
    # ------------------------------------------------------------------

    @property
    def func_dir_pc2(self) -> str:
        """Full path to the func/ directory on PC2."""
        return os.path.join(
            self._root_pc2,
            self.sub_label,
            self.ses_label,
            "func"
        )

    @property
    def func_dir_pc1(self) -> str:
        """Full path to the func/ directory on PC1."""
        return os.path.join(
            self._root_pc1,
            self.sub_label,
            self.ses_label,
            "func"
        )

    def makedirs(self):
        """
        Create both func directories (PC2 only — PC2 must be able to reach both
        or you create them separately on each machine).
        Typically call this on PC2; PC1 creates its own copy via os.makedirs in
        camera_listener.py when the session path is received.
        """
        os.makedirs(self.func_dir_pc2, exist_ok=True)
        print(f"Session folder (PC2): {self.func_dir_pc2}")
        print(f"Session folder (PC1): {self.func_dir_pc1}")

    # ------------------------------------------------------------------
    # Filename construction
    # ------------------------------------------------------------------

    def filename(self, suffix: str) -> str:
        """
        Build the BIDS filename stem (no extension).

        Parameters
        ----------
        suffix : str
            Data type suffix, e.g. "body", "face", "grb", "gb", "events", "frames"

        Returns
        -------
        str
            e.g. "sub-m01_ses-1_task-puff_run-1_body"
        """
        return (
            f"{self.sub_label}"
            f"_{self.ses_label}"
            f"_{self.task_label}"
            f"_{self.run_label}"
            f"_{suffix}"
        )

    def filepath_pc2(self, suffix: str, extension: str) -> str:
        """
        Full file path on PC2.

        Parameters
        ----------
        suffix    : e.g. "body", "events"
        extension : e.g. ".avi", ".tsv", ".yaml"

        Returns
        -------
        str  full absolute path on PC2
        """
        ext = extension if extension.startswith(".") else f".{extension}"
        return os.path.join(self.func_dir_pc2, self.filename(suffix) + ext)

    def filepath_pc1(self, suffix: str, extension: str) -> str:
        """Full file path on PC1."""
        ext = extension if extension.startswith(".") else f".{extension}"
        return os.path.join(self.func_dir_pc1, self.filename(suffix) + ext)

    # ------------------------------------------------------------------
    # Convenience: common file paths
    # ------------------------------------------------------------------

    @property
    def events_tsv_pc2(self) -> str:
        """Behaviour log file path on PC2 (events.tsv)."""
        return self.filepath_pc2("events", ".tsv")

    @property
    def frames_tsv_pc1(self) -> str:
        """Frame timestamp log file path on PC1 (frames.tsv)."""
        return self.filepath_pc1("frames", ".tsv")

    @property
    def body_avi_pc1(self) -> str:
        """ELP body camera AVI path on PC1."""
        return self.filepath_pc1("body", ".avi")

    @property
    def face_avi_pc1(self) -> str:
        """Face camera AVI path on PC1 (future)."""
        return self.filepath_pc1("face", ".avi")

    @property
    def config_yaml_pc2(self) -> str:
        """Config snapshot path on PC2."""
        return self.filepath_pc2("config", ".yaml")

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"BIDSPath("
            f"sub={self.sub_label}, {self.ses_label}, "
            f"{self.task_label}, {self.run_label}"
            f")"
        )

    def summary(self) -> str:
        """Print a summary of all key paths for this session."""
        lines = [
            f"BIDS Session Summary",
            f"  Subject  : {self.sub_label}",
            f"  Session  : {self.ses_label}",
            f"  Task     : {self.task_label}",
            f"  Run      : {self.run_label}",
            f"",
            f"  PC2 func dir : {self.func_dir_pc2}",
            f"  PC1 func dir : {self.func_dir_pc1}",
            f"",
            f"  Events log   : {self.filename('events')}.tsv",
            f"  Frame log    : {self.filename('frames')}.tsv",
            f"  Body camera  : {self.filename('body')}.avi",
            f"  Widefield    : {self.filename('grb')}.tiff  (Andor, named in Solis)",
            f"  Config       : {self.filename('config')}.yaml",
        ]
        return "\n".join(lines)
