"""Workflow registry — discovers and serves workflow presets."""

import importlib
import pkgutil

from . import __name__ as _pkg_name
from .config import WorkflowConfig

_WORKFLOWS: dict[int, WorkflowConfig] = {}


def _discover() -> None:
    """Scan workflow_*.py modules in this package for WORKFLOW instances."""
    if _WORKFLOWS:
        return
    package = importlib.import_module(_pkg_name)
    for info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        if not info.name.rsplit(".", 1)[-1].startswith("workflow_"):
            continue
        mod = importlib.import_module(info.name)
        wf = getattr(mod, "WORKFLOW", None)
        if isinstance(wf, WorkflowConfig):
            _WORKFLOWS[wf.version] = wf


def get_workflow(version: int) -> WorkflowConfig:
    """Get a workflow by version number.

    Raises:
        KeyError: If no workflow with that version exists.
    """
    _discover()
    if version not in _WORKFLOWS:
        raise KeyError(f"No workflow with version {version}")
    return _WORKFLOWS[version]


def list_workflows() -> list[WorkflowConfig]:
    """List all registered workflows, sorted by version."""
    _discover()
    return sorted(_WORKFLOWS.values(), key=lambda w: w.version)
