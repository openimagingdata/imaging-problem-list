from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

class Finding(BaseModel):
    name: str = Field(..., description="Canonical finding name, lowercase (e.g., 'pleural effusion').")
    present: bool = Field(..., description="True if present, False if confidently absent/ruled out.")
    attributes: Optional[List[str]] = Field(default=None, description="Optional descriptors like size, location.")

class ExtractionResult(BaseModel):
    report_id: str
    findings: List[Finding]
