"""
Supabase Storage service for uploading and retrieving proposal files.
"""

import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "proposals")
SIGNED_URL_EXPIRY = 3600  # 1 hour


class StorageService:
    def __init__(self):
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    def upload(self, file_path: str, data: bytes, content_type: str):
        """Upload file bytes to Supabase Storage. Overwrites if exists."""
        try:
            # Try to remove existing file first (ignore errors)
            self.client.storage.from_(BUCKET).remove([file_path])
        except Exception:
            pass

        self.client.storage.from_(BUCKET).upload(
            path=file_path,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )

    def get_signed_url(self, file_path: str) -> str:
        """Generate a signed URL valid for SIGNED_URL_EXPIRY seconds."""
        result = self.client.storage.from_(BUCKET).create_signed_url(
            path=file_path,
            expires_in=SIGNED_URL_EXPIRY,
        )
        return result.get("signedURL") or result.get("signed_url", "")

    def delete_folder(self, folder_prefix: str):
        """Delete all files under a folder prefix."""
        result = self.client.storage.from_(BUCKET).list(folder_prefix)
        if result:
            paths = [f"{folder_prefix}/{item['name']}" for item in result]
            self.client.storage.from_(BUCKET).remove(paths)
