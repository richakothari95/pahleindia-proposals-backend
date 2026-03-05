from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class CreateProposalRequest(BaseModel):
    description: str


class IterateProposalRequest(BaseModel):
    feedback: str


class ProposalResponse(BaseModel):
    id: str
    title: Optional[str]
    description: str
    status: str
    iteration: int
    word_url: Optional[str]
    ppt_url: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str


class GenerationStatusResponse(BaseModel):
    proposal_id: str
    status: str
    stage_message: Optional[str] = None
    word_url: Optional[str] = None
    ppt_url: Optional[str] = None
    error: Optional[str] = None


class IterationResponse(BaseModel):
    id: str
    iteration_num: int
    feedback: Optional[str]
    word_file_path: Optional[str]
    ppt_file_path: Optional[str]
    created_at: str
