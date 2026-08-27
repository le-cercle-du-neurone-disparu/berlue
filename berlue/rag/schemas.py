from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Claim:
    text: str
    source_sentence: str


@dataclass
class Evidence:
    text: str
    label: str
    distance: float
    evidence_id: Optional[int]
    evidence_url: Optional[str]


@dataclass
class RagVerdict:
    verdict: str
    confidence: float
    evidences: List[Evidence]
