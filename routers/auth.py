import os
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

ALLOWED_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "pahleindia.org")
JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")


class ValidateRequest(BaseModel):
    token: str


@router.post("/validate")
def validate_token(body: ValidateRequest):
    try:
        payload = jwt.decode(
            body.token,
            JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    email = payload.get("email", "")
    if not email.endswith(f"@{ALLOWED_DOMAIN}"):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. Only @{ALLOWED_DOMAIN} accounts are permitted.",
        )

    return {
        "valid": True,
        "user_id": payload.get("sub"),
        "email": email,
    }
