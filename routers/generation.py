import os
import asyncio
import json
from fastapi import APIRouter, HTTPException, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import Optional
import jwt

from models.proposal import CreateProposalRequest, IterateProposalRequest
from services.ai_service import AIService
from services.docx_service import DocxService
from services.pptx_service import PptxService
from services.storage_service import StorageService

router = APIRouter()

JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# In-memory store for SSE progress messages
# { proposal_id: asyncio.Queue }
_progress_queues: dict[str, asyncio.Queue] = {}


def get_user_id(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
        return payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_db():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def send_progress(proposal_id: str, status: str, message: str, **kwargs):
    """Push a progress event to the SSE queue for this proposal."""
    if proposal_id in _progress_queues:
        data = {"status": status, "message": message, **kwargs}
        _progress_queues[proposal_id].put_nowait(data)


async def run_generation(proposal_id: str, user_id: str, description: str, feedback: Optional[str] = None):
    db = get_db()
    try:
        # --- Phase 1: Tavily research ---
        send_progress(proposal_id, "researching", "Starting web research...")
        db.table("proposals").update({"status": "researching"}).eq("id", proposal_id).execute()

        ai = AIService()
        decomposed = await ai.decompose(description, feedback)
        send_progress(proposal_id, "researching", f"Research topic: {decomposed['title']}")

        research_corpus = await ai.research(decomposed["queries"], progress_callback=lambda q: send_progress(
            proposal_id, "researching", f"Searching: {q}"
        ))

        # --- Phase 2: AI generation ---
        send_progress(proposal_id, "generating", "Generating proposal content with Claude Opus...")
        db.table("proposals").update({"status": "generating"}).eq("id", proposal_id).execute()

        content = await ai.generate(description, research_corpus, feedback=feedback)

        # Update title from AI output
        db.table("proposals").update({"title": content.title, "ai_content": content.model_dump()}).eq("id", proposal_id).execute()

        # --- Phase 3: Document generation ---
        send_progress(proposal_id, "building", "Building Word document...")
        db.table("proposals").update({"status": "building"}).eq("id", proposal_id).execute()

        # Get current iteration number
        prop = db.table("proposals").select("iteration").eq("id", proposal_id).single().execute()
        current_iter = (prop.data or {}).get("iteration", 0)
        new_iter = current_iter + 1

        docx_svc = DocxService()
        pptx_svc = PptxService()

        word_bytes = docx_svc.generate(content)
        send_progress(proposal_id, "building", "Building PowerPoint presentation...")
        ppt_bytes = pptx_svc.generate(content)

        # --- Phase 4: Upload ---
        send_progress(proposal_id, "building", "Uploading documents...")
        storage = StorageService()

        word_path = f"proposals/{user_id}/{proposal_id}/v{new_iter}/proposal.docx"
        ppt_path = f"proposals/{user_id}/{proposal_id}/v{new_iter}/proposal.pptx"

        storage.upload(word_path, word_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        storage.upload(ppt_path, ppt_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")

        word_url = storage.get_signed_url(word_path)
        ppt_url = storage.get_signed_url(ppt_path)

        # Save iteration record
        db.table("proposal_iterations").insert({
            "proposal_id": proposal_id,
            "iteration_num": new_iter,
            "feedback": feedback,
            "ai_content": content.model_dump(),
            "word_file_path": word_path,
            "ppt_file_path": ppt_path,
        }).execute()

        # Update proposal to ready
        db.table("proposals").update({
            "status": "ready",
            "iteration": new_iter,
            "word_file_path": word_path,
            "ppt_file_path": ppt_path,
            "word_url": word_url,
            "ppt_url": ppt_url,
            "error_message": None,
        }).eq("id", proposal_id).execute()

        send_progress(proposal_id, "ready", "Proposal ready!", word_url=word_url, ppt_url=ppt_url)

    except Exception as e:
        error_msg = str(e)
        db.table("proposals").update({"status": "failed", "error_message": error_msg}).eq("id", proposal_id).execute()
        send_progress(proposal_id, "failed", f"Generation failed: {error_msg}", error=error_msg)
    finally:
        # Clean up queue after a delay
        await asyncio.sleep(60)
        _progress_queues.pop(proposal_id, None)


@router.post("/create")
async def create_proposal(
    body: CreateProposalRequest,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    user_id = get_user_id(authorization)
    db = get_db()

    if len(body.description.strip()) < 50:
        raise HTTPException(status_code=400, detail="Description must be at least 50 characters.")

    # Create proposal record
    result = db.table("proposals").insert({
        "user_id": user_id,
        "description": body.description,
        "status": "pending",
        "iteration": 0,
    }).execute()
    proposal_id = result.data[0]["id"]

    # Create SSE queue
    _progress_queues[proposal_id] = asyncio.Queue()

    # Start background generation
    background_tasks.add_task(run_generation, proposal_id, user_id, body.description)

    return {"proposal_id": proposal_id, "status": "pending"}


@router.get("/{proposal_id}/stream")
async def stream_progress(proposal_id: str, authorization: Optional[str] = Header(None), token: Optional[str] = None):
    # EventSource cannot send headers, so token can also come as query param
    if token and not authorization:
        authorization = f"Bearer {token}"
    user_id = get_user_id(authorization)

    # Ensure queue exists (client might connect slightly after create)
    if proposal_id not in _progress_queues:
        _progress_queues[proposal_id] = asyncio.Queue()

    async def event_generator():
        queue = _progress_queues[proposal_id]
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(data)}\n\n"
                if data.get("status") in ("ready", "failed"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield ": keepalive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{proposal_id}/status")
def get_status(proposal_id: str, authorization: Optional[str] = Header(None)):
    user_id = get_user_id(authorization)
    db = get_db()

    result = db.table("proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found")

    p = result.data
    storage = StorageService()
    word_url = storage.get_signed_url(p["word_file_path"]) if p.get("word_file_path") else None
    ppt_url = storage.get_signed_url(p["ppt_file_path"]) if p.get("ppt_file_path") else None

    return {
        "proposal_id": proposal_id,
        "status": p["status"],
        "word_url": word_url,
        "ppt_url": ppt_url,
        "error": p.get("error_message"),
    }


@router.post("/{proposal_id}/iterate")
async def iterate_proposal(
    proposal_id: str,
    body: IterateProposalRequest,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    user_id = get_user_id(authorization)
    db = get_db()

    result = db.table("proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = result.data
    if proposal["status"] not in ("ready", "failed"):
        raise HTTPException(status_code=400, detail="Proposal is not in a state that can be iterated.")

    # Reset status
    db.table("proposals").update({"status": "pending"}).eq("id", proposal_id).execute()

    # Create new SSE queue
    _progress_queues[proposal_id] = asyncio.Queue()

    background_tasks.add_task(
        run_generation, proposal_id, user_id, proposal["description"], feedback=body.feedback
    )

    return {"proposal_id": proposal_id, "status": "pending", "iteration": proposal["iteration"]}


@router.post("/{proposal_id}/done")
def mark_done(proposal_id: str, authorization: Optional[str] = Header(None)):
    user_id = get_user_id(authorization)
    db = get_db()

    result = db.table("proposals").select("id").eq("id", proposal_id).eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found")

    db.table("proposals").update({"status": "ready"}).eq("id", proposal_id).execute()
    return {"proposal_id": proposal_id, "finalised": True}
