"""Live smoke test for the Gemini Live credential mint.

Hits the real ``auth_tokens.create`` endpoint, which is the one thing the
offline suite cannot check: whether the vendor actually accepts a whole
:class:`~google.genai.types.LiveConnectConfig` inside ``live_connect_constraints``
on this model. If it does not, the offline tests still pass and the Voice button
still fails in the browser — so this runs before shipping a model-id change.

Nothing is spoken and no session is opened: minting is the surface under test.
The token this prints is short-lived, single-purpose and not worth guarding, but
it is still a credential — it is not logged in full.

Run:  .venv/bin/python tests/test_gemini_live_mint.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candidate_agent.voice import build_gemini_live_session
from llm.factory import DEFAULT_REALTIME_MODEL_IDS
from llm.gemini_live import GEMINI_LIVE_VOICES, GeminiLiveBroker
from tests.test_session import CONTRACT

load_dotenv()

TTL_SECONDS = 600


async def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("SKIP: GEMINI_API_KEY is not set")
        return 0

    model_id = os.getenv("VOICE_MODEL") or DEFAULT_REALTIME_MODEL_IDS["gemini"]
    broker = GeminiLiveBroker(model_id, api_key)
    session = build_gemini_live_session(CONTRACT, voices=broker.voices)

    print(f"Minting against {model_id} ...")
    credential = await broker.mint(session=session, ttl_seconds=TTL_SECONDS)

    failures: list[str] = []
    if not credential.value:
        failures.append("no token returned")
    if credential.model != model_id:
        failures.append(f"credential names {credential.model!r}, not the model we minted against")
    if credential.call_url:
        failures.append("the Live API has no call URL; the SDK owns the endpoint")
    if credential.expires_at <= int(time.time()):
        failures.append(f"token already expired at {credential.expires_at}")
    if session["voice"] not in GEMINI_LIVE_VOICES:
        failures.append(f"voice {session['voice']!r} is not on the roster")

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"  PASS  token {credential.value[:18]}… expires {credential.expires_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
