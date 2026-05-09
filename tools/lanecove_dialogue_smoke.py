"""
lanecove_dialogue_smoke.py — Real LLM × shared memories face-validity smoke.

Purpose: verify that when Lane Cove shared_memories are injected into a
protagonist's MemoryService, the dialogue prompts that handle_generate_message
builds end up actually feeding those memories to the LLM, AND the LLM uses
them in its output.

This is the cheapest test of:
1. Does the retrieval path surface shared_memory events when ranking by
   importance? (yes per unit tests, but never tried with a real LLM)
2. Does the LLM actually weave them into dialogue?
   (i.e. does "shared memories" investment pay off for face validity?)

Cost: ~$0 with Gemini flash, ~$0.5 with Anthropic Haiku.

Usage:
    python3 tools/lanecove_dialogue_smoke.py                  # default Gemini
    python3 tools/lanecove_dialogue_smoke.py --provider anthropic
    python3 tools/lanecove_dialogue_smoke.py --turns 4        # multi-turn
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow `import tools.suite_stub_llm` from script context
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic_socio_wind_tunnel.agent.operations.handlers import (
    handle_generate_message,
    handle_remember_conversation,
)
from synthetic_socio_wind_tunnel.agent.operations.handlers.generate_message import (
    _build_continue_prompt,
    _build_start_prompt,
)
from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp
from synthetic_socio_wind_tunnel.data_loader import (
    load_shared_memories,
    inject_shared_memories_into_agent,
)
from synthetic_socio_wind_tunnel.memory.models import MemoryQuery
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from tools.suite_stub_llm import _AnthropicClient, _GeminiClient  # type: ignore[import]


# Two character profiles — one rooted, one new
EMMA_IDENTITY = (
    "Emma is a 32-year-old Lane Cove librarian who's lived on Longueville Road "
    "for eight years. She's quietly observant, prefers regular routines, "
    "and treats the local library as her second home. She follows council "
    "news closely and can usually tell you which café changed hands last."
)
EMMA_PLAN = (
    "Catch up with neighbours about the weekend's Food and Wine by the River "
    "and find out if anyone's been to the new Galuwa rec centre yet."
)

LINDA_IDENTITY = (
    "Linda is a 29-year-old data scientist who moved to Lane Cove from "
    "Beijing six months ago. She's still figuring out which bus to catch, "
    "warm but reserved with strangers, and treats Stringybark Creek like a "
    "lifeline for her morning runs."
)
LINDA_PLAN = (
    "Find out which of her neighbours actually go to community events — "
    "she's tired of doing weekends solo."
)


def _load_env_dotenv() -> None:
    """Best-effort .env loader (no python-dotenv dep)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _make_llm_client(provider: str):
    """Build an LLM client for whichever provider has a key in env."""
    if provider == "anthropic":
        return _AnthropicClient(model="claude-haiku-4-5-20251001")
    if provider == "gemini":
        return _GeminiClient(model="gemini-3-flash-preview")
    if provider == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return _AnthropicClient(model="claude-haiku-4-5-20251001"), "anthropic"
        if os.environ.get("GEMINI_API_KEY"):
            return _GeminiClient(model="gemini-3-flash-preview"), "gemini"
        raise RuntimeError(
            "no API key found. Set ANTHROPIC_API_KEY or GEMINI_API_KEY in .env."
        )
    raise ValueError(f"unknown provider {provider!r}")


def _build_args(
    speaker: str,
    speaker_name: str,
    speaker_identity: str,
    speaker_plan: str,
    other: str,
    other_name: str,
    other_identity: str,
    relevant_memories: list[str],
    recent_messages: list[tuple[str, str]],
    phase: str,
    *,
    dialogue_id: str = "smoke_d1",
) -> dict:
    return dict(
        dialogue_id=dialogue_id,
        speaker_id=speaker,
        speaker_name=speaker_name,
        speaker_identity=speaker_identity,
        speaker_plan=speaker_plan,
        other_agent_id=other,
        other_name=other_name,
        other_identity=other_identity,
        recent_messages=recent_messages,
        relevant_memories=relevant_memories,
        phase=phase,
    )


def _hits_shared_memory(text: str, memories: list[str]) -> list[str]:
    """Return shared memory titles whose distinctive keywords appear in `text`.
    Heuristic — picks ≥2-char Chinese keywords + place names from each memory.
    """
    distinctive = {
        "lc_mem_001": ["Galuwa", "rec centre", "球场"],
        "lc_mem_002": ["Tunnel", "起重机", "起火", "隧道"],
        "lc_mem_003": ["毒树", "Longueville", "海港", "树"],
        "lc_mem_004": ["Crows Nest", "Metro", "地铁"],
        "lc_mem_005": ["St Leonards", "高密度", "重新规划"],
        "lc_mem_006": ["最宜居", "liveable", "宜居"],
        "lc_mem_007": ["Food and Wine", "Burns Bay", "酒"],
        "lc_mem_008": ["Rotary", "Sustainability", "市集"],
        "lc_mem_009": ["St Leonards Library", "Christie", "图书馆"],
        "lc_mem_010": ["Greenwich", "Wharf", "F8", "渡轮"],
        "lc_mem_011": ["Pottery Lane", "performance", "剧场"],
        "lc_mem_012": ["封城", "lockdown", "Delta"],
    }
    hits: list[str] = []
    text_low = text.lower()
    for mid, keywords in distinctive.items():
        if any(k.lower() in text_low for k in keywords):
            hits.append(mid)
    return hits


async def _run_smoke(provider: str, num_turns: int, top_k: int) -> int:
    _load_env_dotenv()

    if provider == "auto":
        client, provider = _make_llm_client("auto")
    else:
        client = _make_llm_client(provider)

    print(f"[setup] provider={provider}, top_k={top_k}, turns={num_turns}")
    print(f"[setup] client class: {type(client).__name__}")

    # 1. Load shared memories + inject into emma
    recs = load_shared_memories()
    print(f"[setup] loaded {len(recs)} shared memories from data/lanecove/")

    msvc = MemoryService()
    inject_shared_memories_into_agent(
        "emma", recs, memory_service=msvc,
    )
    all_evs = msvc.all_for("emma")
    print(f"[setup] emma's memory store: {len(all_evs)} shared_memory events\n")

    # 2. Retrieve top-k by importance — this is what dialogue prompts use.
    top = msvc.retrieve(
        "emma", MemoryQuery(kind="shared_memory"), top_k=top_k,
    )
    relevant_memories = [ev.content for ev in top]
    print(f"[retrieval] top-{top_k} memories fed to prompt:")
    for ev in top:
        print(f"  - [imp={ev.importance:.2f}] {ev.content[:90]}...")
    print()

    # 3. Build dialogue prompt args + first message (phase=start, emma initiates)
    print("=" * 78)
    print("Turn 1 — emma to linda (phase=start)")
    print("=" * 78)
    start_args = _build_args(
        "emma", "Emma", EMMA_IDENTITY, EMMA_PLAN,
        "linda", "Linda", LINDA_IDENTITY,
        relevant_memories, [], "start",
    )
    start_prompt = _build_start_prompt(start_args)
    print(f"[prompt] {len(start_prompt)} chars; first 600:")
    print("-" * 60)
    print(start_prompt[:600])
    print("...")
    print("-" * 60)

    op_emma_start = PendingOp(
        op_id="op_emma_start", agent_id="emma", kind="generate_message",
        created_tick=10, timeout_tick=34, args=start_args,
    )
    result = await handle_generate_message(op_emma_start, llm_client=client)
    if not result.success:
        print(f"[error] {result.error_msg}")
        return 1
    emma_first = result.payload["content"]
    print(f"[Emma → Linda] {emma_first}")
    hits = _hits_shared_memory(emma_first, relevant_memories)
    if hits:
        print(f"  ✓ shared memories cited: {hits}")
    else:
        print(f"  ⚠ no clear shared-memory citation in first message")
    print()

    if num_turns < 2:
        return 0

    # 4. Pretend linda replies, then emma's continuation
    fake_linda_reply = "Oh nice to meet you. I just moved here a few months ago."
    print("=" * 78)
    print(f"Turn 2 — linda to emma (FAKE for smoke): \"{fake_linda_reply}\"")
    print("=" * 78)
    history: list[tuple[str, str]] = [
        ("Emma", emma_first),
        ("Linda", fake_linda_reply),
    ]

    print()
    print("=" * 78)
    print("Turn 3 — emma to linda (phase=continue)")
    print("=" * 78)
    cont_args = _build_args(
        "emma", "Emma", EMMA_IDENTITY, EMMA_PLAN,
        "linda", "Linda", LINDA_IDENTITY,
        relevant_memories, history, "continue",
    )
    cont_prompt = _build_continue_prompt(cont_args)
    print(f"[prompt] {len(cont_prompt)} chars; full prompt:")
    print("-" * 60)
    print(cont_prompt)
    print("-" * 60)

    op_emma_cont = PendingOp(
        op_id="op_emma_cont", agent_id="emma", kind="generate_message",
        created_tick=11, timeout_tick=35, args=cont_args,
    )
    result = await handle_generate_message(op_emma_cont, llm_client=client)
    if not result.success:
        print(f"[error] {result.error_msg}")
        return 1
    emma_second = result.payload["content"]
    print(f"[Emma → Linda] {emma_second}")
    hits2 = _hits_shared_memory(emma_second, relevant_memories)
    if hits2:
        print(f"  ✓ shared memories cited: {hits2}")
    else:
        print(f"  ⚠ no clear shared-memory citation in continuation")
    print()

    # 5. Final summary
    all_text = emma_first + " " + emma_second
    all_hits = _hits_shared_memory(all_text, relevant_memories)
    print("=" * 78)
    print("Smoke Result")
    print("=" * 78)
    print(f"Total emma turns: 2")
    print(f"Shared memory citations across both turns: {len(all_hits)}")
    print(f"  -> {all_hits}")
    if not all_hits:
        print()
        print("  ⚠ ZERO citations. Possible causes:")
        print("    1. LLM ignored 'Relevant memories' section (prompt structure issue)")
        print("    2. Shared memories don't fit conversation flow naturally")
        print("    3. Emma's identity/plan didn't motivate referencing them")
    elif len(all_hits) == 1:
        print()
        print("  ✓ Light citation — natural-sounding, not heavy-handed.")
    else:
        print()
        print(f"  ✓ Multiple ({len(all_hits)}) citations — shared memories DO surface.")

    # 6. Optionally test remember_conversation summary too
    print()
    print("=" * 78)
    print("Bonus — remember_conversation(emma's perspective)")
    print("=" * 78)
    op_remember = PendingOp(
        op_id="op_emma_remember", agent_id="emma",
        kind="remember_conversation",
        created_tick=20, timeout_tick=44,
        args={
            "dialogue_id": "smoke_d1",
            "speaker_id": "emma",
            "speaker_name": "Emma",
            "other_name": "Linda",
            "messages": [
                ("emma", emma_first),
                ("linda", fake_linda_reply),
                ("emma", emma_second),
            ],
        },
    )
    rem_result = await handle_remember_conversation(op_remember, llm_client=client)
    if rem_result.success:
        print(f"[Emma's summary] {rem_result.payload['summary']}")
    else:
        print(f"[error] {rem_result.error_msg}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider", choices=["auto", "anthropic", "gemini"],
                   default="auto",
                   help="auto picks anthropic > gemini based on API key in .env")
    p.add_argument("--turns", type=int, default=2,
                   help="emma's number of turns (1 or 2; default 2)")
    p.add_argument("--top-k", type=int, default=4,
                   help="how many shared memories feed into each prompt")
    args = p.parse_args()
    return asyncio.run(_run_smoke(
        provider=args.provider,
        num_turns=args.turns,
        top_k=args.top_k,
    ))


if __name__ == "__main__":
    sys.exit(main())
