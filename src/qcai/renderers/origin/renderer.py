"""Origin 2024b renderer delegating to an isolated serial worker subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from qcai.interfaces.renderer import FigureRenderer
from qcai.renderers.spec import FigureSpec


class OriginRenderer(FigureRenderer):
    """Render FigureSpec via Origin 2024b in an isolated subprocess with timeout."""

    name = "origin"
    _lock = threading.Lock()

    def __init__(
        self,
        *,
        templates_dir: Path | None = None,
        timeout_seconds: float = 90.0,
        max_attempts: int = 2,
    ) -> None:
        self.templates_dir = templates_dir or (Path(__file__).resolve().parent / "templates")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def render(self, spec: FigureSpec, out_dir: Path) -> list[Path]:
        if sys.platform != "win32":
            raise RuntimeError("OriginRenderer is only supported on Windows")

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            last_error: Exception | None = None
            for attempt in range(1, self.max_attempts + 1):
                try:
                    return self._run_once(spec, out_dir)
                except (subprocess.TimeoutExpired, RuntimeError) as exc:
                    last_error = exc
                    if attempt == self.max_attempts:
                        break
            raise RuntimeError(
                f"Origin rendering failed after {self.max_attempts} attempts: {last_error}"
            ) from last_error

    def _run_once(self, spec: FigureSpec, out_dir: Path) -> list[Path]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_file = Path(tmp_dir) / "spec.json"
            spec_file.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
            cmd = [
                sys.executable,
                "-m",
                "qcai.renderers.origin.worker",
                str(spec_file),
                str(out_dir),
                str(self.templates_dir) if self.templates_dir else "",
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Origin worker exited with code {proc.returncode}: {proc.stderr.strip()}"
                )
            lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            if not lines:
                raise RuntimeError("Origin worker produced no output paths")
            paths = [Path(p) for p in json.loads(lines[-1])]
            for p in paths:
                if not p.exists() or p.stat().st_size == 0:
                    raise RuntimeError(f"Expected Origin output missing or empty: {p}")
            return paths
