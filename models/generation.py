from pydantic import BaseModel, Field
from typing import List, Optional


class ObjectiveItem(BaseModel):
    number: int
    text: str


class ResultItem(BaseModel):
    heading: str
    content: str
    data_point: str


class TakeawayItem(BaseModel):
    number: int
    actor: str
    recommendation: str


class GlossaryItem(BaseModel):
    term: str
    definition: str


class SourceItem(BaseModel):
    title: str
    url: str
    date: str


class PPTSlide(BaseModel):
    slide_number: int
    slide_type: str  # "title" | "section_header" | "content" | "thank_you"
    title: str
    subtitle: Optional[str] = None
    body_points: List[str] = Field(default_factory=list)
    data_callout: Optional[str] = None


class ProposalContent(BaseModel):
    title: str
    subtitle: str
    authors: str
    executive_summary: str
    problem_statement: str
    policy_context: str
    objectives: List[ObjectiveItem]
    methodology: str
    results: List[ResultItem]
    takeaways: List[TakeawayItem]
    conclusion: str
    glossary: List[GlossaryItem] = Field(default_factory=list)
    annexures: Optional[str] = None
    sources: List[SourceItem] = Field(default_factory=list)
    ppt_slides: List[PPTSlide] = Field(default_factory=list)
