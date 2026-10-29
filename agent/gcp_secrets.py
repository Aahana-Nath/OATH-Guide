"""Fetch the Gemini API key from GCP Secret Manager (Python port of getGeminiApiKey in secrets.ts).

Order: Secret Manager (secret `gemini_api_key`, version latest) when GCP_PROJECT_ID is set,
then the GEMINI_API_KEY environment variable / .env. Auth uses Application Default Credentials:
  gcloud auth application-default login
"""
import os
import sys

SECRET_NAME = os.environ.get("GEMINI_SECRET_NAME", "gemini_api_key")
_cached = None


def _log(msg):
    print(f"[secrets] {msg}", file=sys.stderr, flush=True)


def get_gemini_api_key():
    """Return the Gemini API key, or '' if none can be found. Never logs the key itself."""
    global _cached
    if _cached:
        return _cached
    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if project:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project}/secrets/{SECRET_NAME}/versions/latest"
            payload = client.access_secret_version(request={"name": name}, timeout=20).payload.data.decode("utf-8").strip()
            if payload:
                _log(f"fetched Gemini API key from Secret Manager ({SECRET_NAME})")
                _cached = payload
                return payload
        except ImportError:
            _log("google-cloud-secret-manager not installed (pip install google-cloud-secret-manager); using environment")
        except Exception as e:
            _log(f"Secret Manager unavailable, using environment: {type(e).__name__}: {str(e)[:160]}")
    return os.environ.get("GEMINI_API_KEY", "").strip()
