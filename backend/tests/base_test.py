"""
Base class for all WCAG tests.
Each test yields progress dicts via async generator so the API can stream them.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Optional
from datetime import datetime


@dataclass
class TestResult:
    test_id: str
    test_name: str
    result: str  # "pass" | "fail" | "warning" | "error"
    wcag_criteria: list[str]
    severity: str  # "critical" | "major" | "minor"
    failure_reason: str = ""
    recommendation: str = ""
    screenshot_path: Optional[str] = None
    screenshot_b64: Optional[str] = None
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class BaseWCAGTest:
    TEST_ID: str = ""
    TEST_NAME: str = ""
    WCAG_CRITERIA: list[str] = []
    DEFAULT_SEVERITY: str = "major"

    def __init__(self, agent, run_dir: Path, pointer=None):
        self.agent = agent
        self.run_dir = run_dir
        self.pointer = pointer  # Optional Molmo2Pointer for visual confirmation

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        """
        Yield progress dicts:
          { "type": "progress", "message": "..." }
          { "type": "result", "data": TestResult.__dict__ }
        """
        raise NotImplementedError

    def _progress(self, message: str) -> dict:
        return {"type": "progress", "test": self.TEST_ID, "message": message}

    def _result(self, result: TestResult) -> dict:
        return {"type": "result", "test": self.TEST_ID, "data": result.__dict__}
