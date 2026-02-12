"""Workflow 0 — MVP baseline capturing current pipeline defaults."""

from .config import WorkflowConfig

WORKFLOW = WorkflowConfig(
    name="Workflow 0",
    description="MVP baseline — stock video + Edge TTS + Montserrat subs",
    version=0,
)
