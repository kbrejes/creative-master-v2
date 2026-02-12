"""Workflow preset system — named pipeline configurations."""

from .config import WorkflowConfig
from .registry import get_workflow, list_workflows

__all__ = ["WorkflowConfig", "get_workflow", "list_workflows"]
