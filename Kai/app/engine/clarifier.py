"""Clarifier — evaluates if a user request is specific enough for pipeline creation.

When the request is ready, synthesises the full conversation into an enhanced prompt
that captures every detail gathered during Q&A so the downstream decomposer has
maximum context.
"""

from app.llm.service import call_llm_messages, parse_json_output

SYSTEM_PROMPT = """\
You are a pipeline-creation assistant. Your job is to evaluate whether the user's \
request is specific enough to create an automation pipeline.

IMPORTANT — the system has built-in capabilities including:
- Web search and scraping (can look up any public information, prices, news, etc.)
- LLM-powered text processing (summarisation, analysis, scoring, formatting)
- Notifications and email

Do NOT ask the user where to find information or which sources to use — assume the \
system can search the web and retrieve what it needs. Only ask clarifying questions \
about the user's actual goal or preferences that cannot be inferred.

A request is "ready" if it includes:
- A clear action or sequence of actions to perform
- Enough context to understand the user's goal

A request is NOT ready if it's:
- Too vague (e.g., "automate something", "help me with work")
- Missing critical details about the user's goal that cannot be inferred

If the request is NOT ready, ask ONE short clarifying question to get the missing detail.
You may ask at most 3 rounds of questions total. After 3 rounds, consider the request \
ready and work with what you have.

Respond in JSON only:
- If ready: {"ready": true, "refined_intent": "<enhanced prompt — see below>"}
- If not ready: {"ready": false, "question": "<your clarifying question>"}

## Enhanced Prompt (refined_intent) — IMPORTANT
When the request IS ready, the refined_intent must be a comprehensive, detailed \
specification that a task-decomposer can act on. Synthesise EVERYTHING from the \
conversation into a single rich prompt. Include:

1. **Goal**: What the user wants to achieve, stated clearly.
2. **Steps / Actions**: The concrete sequence of actions implied or stated.
3. **Inputs & Parameters**: Any specific values, thresholds, preferences, or \
   constraints the user mentioned (e.g. budget amounts, specific sources, \
   frequency, recipients).
4. **Output / Deliverable**: What the end result should look like.
5. **Edge Cases & Preferences**: Any preferences or special handling the user \
   mentioned during clarification.

Write it as a detailed, self-contained instruction — not a conversation summary. \
The downstream system will never see the conversation, only this enhanced prompt."""


ENHANCE_SYSTEM_PROMPT = """\
You are a prompt enhancer. You are given a conversation between a user and an \
assistant about creating an automation pipeline. Your job is to synthesise the \
ENTIRE conversation into a single, comprehensive, self-contained enhanced prompt \
that a task-decomposer can act on.

Include:
1. **Goal**: What the user wants to achieve.
2. **Steps / Actions**: The concrete sequence of actions implied or stated.
3. **Inputs & Parameters**: Specific values, thresholds, preferences, constraints.
4. **Output / Deliverable**: What the end result should look like.
5. **Edge Cases & Preferences**: Any special handling mentioned.

Write it as a detailed instruction, not a summary. Output ONLY the enhanced prompt \
text — no JSON, no markdown fences, no preamble."""


async def _enhance_from_conversation(messages: list[dict]) -> str:
    """Take the full conversation and produce an enhanced prompt via a second LLM call."""
    # Build a transcript of the conversation (skip system messages)
    turns = []
    for msg in messages:
        if msg["role"] == "system":
            continue
        label = "User" if msg["role"] == "user" else "Assistant"
        turns.append(f"{label}: {msg['content']}")
    transcript = "\n".join(turns)

    enhance_messages = [
        {"role": "system", "content": ENHANCE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Here is the conversation:\n\n{transcript}\n\nProduce the enhanced prompt."},
    ]
    return await call_llm_messages(enhance_messages)


async def clarify(message: str, history: list[dict]) -> dict:
    """Evaluate if the user's request is specific enough.

    Returns {"ready": True, "refined_intent": "..."} or {"ready": False, "question": "..."}
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add current message
    messages.append({"role": "user", "content": message})

    # If we've already had 3+ user messages, force ready — enhance from conversation
    user_count = sum(1 for m in messages if m["role"] == "user")
    if user_count > 3:
        enhanced = await _enhance_from_conversation(messages)
        return {"ready": True, "refined_intent": enhanced}

    response = await call_llm_messages(messages)

    try:
        parsed = parse_json_output(response)
        if "ready" in parsed:
            return parsed
    except Exception:
        pass

    # Fallback: enhance from conversation context rather than losing it
    enhanced = await _enhance_from_conversation(messages)
    return {"ready": True, "refined_intent": enhanced}
