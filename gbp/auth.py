"""Google OAuth for the Business Profile APIs.

One scope covers every Business Profile API: `business.manage`. There is no
finer-grained scope, which is worth knowing before you connect an account --
this token can read and write everything on every location that account
manages.

The refresh token is written to data/token.json and reused forever after, so
the browser consent screen appears exactly once.

THE SEVEN DAY TRAP
------------------
While your OAuth consent screen is in **Testing** mode, Google expires refresh
tokens after 7 days. The agent then dies every week with
`invalid_grant: Token has been expired or revoked` and you have to log in
again. This is not a bug in this tool and no amount of retrying fixes it.

The fix is to publish the consent screen:
    Google Cloud Console -> APIs & Services -> OAuth consent screen -> PUBLISH APP

You do NOT need Google to verify the app for your own use. Publishing alone
stops the 7-day expiry. `run.py doctor` checks for this and says so plainly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

from . import config

SCOPES = ["https://www.googleapis.com/auth/business.manage"]

# Every Business Profile API host, and what each one is for. Reviews, posts
# (localPosts) and media still live on the LEGACY v4 host -- Google never
# migrated them -- and v4 requires separately approved access.
HOSTS = {
    "account": "https://mybusinessaccountmanagement.googleapis.com/v1",
    "info": "https://mybusinessbusinessinformation.googleapis.com/v1",
    "legacy": "https://mybusiness.googleapis.com/v4",
    "performance": "https://businessprofileperformance.googleapis.com/v1",
    "qanda": "https://mybusinessqanda.googleapis.com/v1",
    "placeactions": "https://mybusinessplaceactions.googleapis.com/v1",
    "notifications": "https://mybusinessnotifications.googleapis.com/v1",
    "verifications": "https://mybusinessverifications.googleapis.com/v1",
}


class AuthError(RuntimeError):
    """Raised with a message a non-developer can act on."""


def _load_saved() -> Credentials | None:
    if not config.TOKEN_PATH.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(config.TOKEN_PATH), SCOPES)
    except (ValueError, json.JSONDecodeError):
        # A corrupt token file is not worth a stack trace; just re-auth.
        return None


def _save(creds: Credentials) -> None:
    config.ensure_dirs()
    config.TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    # The token file is a live key to the account. Best effort on POSIX;
    # Windows inherits the folder ACL and there is no chmod equivalent.
    try:
        config.TOKEN_PATH.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def credentials(interactive: bool = True) -> Credentials:
    """Return usable credentials, refreshing or prompting as needed.

    interactive=False is for scheduled runs: it will refresh a saved token but
    never try to open a browser on a machine nobody is sitting at.
    """
    creds = _load_saved()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception as exc:  # google auth raises several unrelated types
            if "invalid_grant" in str(exc):
                raise AuthError(
                    "Your Google login has expired.\n\n"
                    "  This is the 7-day Testing-mode expiry, not a real error.\n"
                    "  Permanent fix (2 minutes, once):\n"
                    "    Google Cloud Console -> APIs & Services -> OAuth consent screen\n"
                    "    -> PUBLISH APP\n\n"
                    "  Then run:  python run.py login"
                ) from exc
            raise AuthError(f"Could not refresh the Google login: {exc}") from exc

    if not interactive:
        raise AuthError(
            "No usable Google login, and this run is non-interactive.\n"
            "  Run `python run.py login` from a machine with a browser first."
        )

    if not config.CLIENT_SECRET_PATH.exists():
        raise AuthError(
            f"{config.CLIENT_SECRET_PATH.name} is missing.\n\n"
            "  Download it from Google Cloud Console -> APIs & Services\n"
            "  -> Credentials -> your OAuth 2.0 Client ID -> Download JSON,\n"
            f"  and save it as:  {config.CLIENT_SECRET_PATH}\n\n"
            "  Full walkthrough is in the README, Step 2."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.CLIENT_SECRET_PATH), SCOPES
    )
    # port=0 lets the OS pick a free port, so a leftover process never blocks
    # the callback. access_type/prompt together are what actually produce a
    # refresh token -- without them Google returns an access token only.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Opening your browser to sign in to Google...",
        success_message="Signed in. You can close this tab and go back to the terminal.",
    )
    _save(creds)
    return creds


# --------------------------------------------------------------- web sign-in

def _client_config() -> dict:
    if not config.CLIENT_SECRET_PATH.exists():
        raise AuthError(
            f"{config.CLIENT_SECRET_PATH.name} is missing.\n\n"
            "  Download it from Google Cloud Console -> APIs & Services\n"
            "  -> Credentials -> your OAuth 2.0 Client ID -> Download JSON,\n"
            f"  and save it as:  {config.CLIENT_SECRET_PATH}")
    return json.loads(config.CLIENT_SECRET_PATH.read_text(encoding="utf-8"))


def auth_url(redirect_uri: str, state: str) -> str:
    """The Google consent URL for the web app's sign-in.

    The CLI uses `run_local_server`, which spins up its own server and blocks
    until the callback arrives. That is wrong for a web app: the request would
    hang, and -- worse -- if a valid token already exists it returns instantly
    without ever showing a browser, so "sign in as a different account" does
    nothing at all. This builds the URL instead and lets the app own the
    redirect.

    `prompt="select_account consent"` is what makes switching accounts work:
    without it Google silently reuses whoever is already signed in.
    """
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES,
                                   redirect_uri=redirect_uri)
    url, _ = flow.authorization_url(
        access_type="offline",          # ask for a refresh token
        prompt="select_account consent",  # always show the picker
        include_granted_scopes="true",
        state=state,
    )
    return url


def exchange(code: str, redirect_uri: str) -> Credentials:
    """Swap the callback's code for credentials, and save them.

    Google's rejections here are terse and all look the same from the outside,
    so they are translated into the thing you actually have to go and do.
    """
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES,
                                   redirect_uri=redirect_uri)
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        detail = str(exc)
        # oauthlib puts Google's JSON body on the exception; pull the useful
        # part out rather than showing the whole traceback.
        if "invalid_grant" in detail:
            raise AuthError(
                "Google rejected the sign-in code (invalid_grant).\n\n"
                "  This almost always means one of:\n"
                "   1. The code was already used. Each sign-in link works ONCE "
                "-- do not reload\n      the callback page or press back. Start "
                "again from Connect.\n"
                "   2. The link sat unused for more than a few minutes.\n"
                "   3. This machine's clock is wrong. Google signs the code "
                "against real time,\n      so even a couple of minutes of drift "
                "fails. Check Windows time sync.\n"
                "   4. Your Google account is not a Test User on the OAuth "
                "consent screen,\n      while that screen is still in Testing "
                "mode.\n\n"
                f"  Google said: {detail[:300]}") from exc
        if "invalid_client" in detail:
            raise AuthError(
                "Google did not recognise this app (invalid_client).\n"
                "  data/client_secret.json does not match the OAuth client in "
                "Cloud Console.\n"
                f"  Google said: {detail[:200]}") from exc
        if "redirect_uri_mismatch" in detail:
            raise AuthError(
                f"Google refused the redirect address {redirect_uri}.\n"
                "  The OAuth client must be a DESKTOP type, which accepts any "
                "loopback port.\n"
                "  A Web application client would need this exact URI "
                "registered.\n"
                f"  Google said: {detail[:200]}") from exc
        raise AuthError(f"Could not complete the sign-in: {detail[:400]}") from exc

    creds = flow.credentials
    if not creds.refresh_token:
        # Without one the login dies at the first expiry and cannot renew.
        raise AuthError(
            "Google returned no refresh token.\n"
            "  Remove this app at https://myaccount.google.com/permissions "
            "and sign in again.")
    _save(creds)
    return creds


def sign_out() -> bool:
    """Forget the saved login. The next sign-in starts from the account picker."""
    if config.TOKEN_PATH.exists():
        config.TOKEN_PATH.unlink()
        return True
    return False


def token_age_days() -> float | None:
    """How long ago we last wrote a token. Used by `doctor` to warn about the
    7-day Testing-mode expiry before it bites, rather than after."""
    if not config.TOKEN_PATH.exists():
        return None
    return (time.time() - config.TOKEN_PATH.stat().st_mtime) / 86400.0
