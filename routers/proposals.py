import os
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
import jwt

from services.storage_service import StorageService

router = APIRouter()

JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def get_user_id(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
        return payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_supabase_client():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


@router.get("")
def list_proposals(authorization: Optional[str] = Header(None)):
    user_id = get_user_id(authorization)
    db = get_supabase_client()
    result = (
        db.table("proposals")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    proposals = result.data or []

    # Refresh signed URLs for ready proposals
    storage = StorageService()
    for p in proposals:
        if p.get("status") == "ready":
            if p.get("word_file_path"):
                p["word_url"] = storage.get_signed_url(p["word_file_path"])
            if p.get("ppt_file_path"):
                p["ppt_url"] = storage.get_signed_url(p["ppt_file_path"])

    return proposals


@router.get("/{proposal_id}")
def get_proposal(proposal_id: str, authorization: Optional[str] = Header(None)):
    user_id = get_user_id(authorization)
    db = get_supabase_client()

    result = db.table("proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = result.data

    # Refresh signed URLs
    storage = StorageService()
    if proposal.get("status") == "ready":
        if proposal.get("word_file_path"):
            proposal["word_url"] = storage.get_signed_url(proposal["word_file_path"])
        if proposal.get("ppt_file_path"):
            proposal["ppt_url"] = storage.get_signed_url(proposal["ppt_file_path"])

    # Get iterations
    iter_result = (
        db.table("proposal_iterations")
        .select("*")
        .eq("proposal_id", proposal_id)
        .order("iteration_num")
        .execute()
    )
    proposal["iterations"] = iter_result.data or []

    return proposal


@router.delete("/{proposal_id}")
def delete_proposal(proposal_id: str, authorization: Optional[str] = Header(None)):
    user_id = get_user_id(authorization)
    db = get_supabase_client()

    result = db.table("proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = result.data
    storage = StorageService()

    # Delete all files under this proposal's folder
    try:
        folder = f"proposals/{user_id}/{proposal_id}"
        storage.delete_folder(folder)
    except Exception:
        pass

    db.table("proposals").delete().eq("id", proposal_id).execute()
    return {"deleted": True}
