import base64
import json
import re

from openai import AsyncOpenAI

_SYSTEM_TEMPLATE = """\
You are a proactive visual monitoring assistant embedded in a security camera system.

## YOUR ROLE
Analyze the provided camera frame and produce a single structured JSON observation.

## MONITORING INSTRUCTIONS
{instructions}

## RESPONSE RULES
- Return ONLY valid JSON — no prose, no markdown fences.
- Use "ignore" when nothing relevant is happening; keep message empty.
- Use "comment" for noteworthy but non-urgent observations.
- Use "alert" for any condition listed as an immediate alert trigger.
- Avoid repeating what was already reported in the recent history below.
- Be concise: one clear sentence for message is enough.

## REQUIRED OUTPUT FORMAT
{{"type": "ignore"|"comment"|"alert", "message": "string", "tags": ["string"]}}

## RECENT OBSERVATION HISTORY
{history}
"""


class Analyzer:
    def __init__(self, config: dict):
        api_cfg = config.get("api", {})
        self._client = AsyncOpenAI(
            api_key=api_cfg.get("api_key"),
            base_url=api_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            timeout=api_cfg.get("timeout_seconds", 20),
        )
        self._model = api_cfg.get("model", "qwen-vl-plus")
        self._max_tokens = api_cfg.get("max_tokens", 300)
        self._monitoring = config.get("monitoring", {})

    async def analyze(self, frame_jpeg: bytes, history: list[dict]) -> dict:
        b64 = base64.b64encode(frame_jpeg).decode()
        instructions = self._monitoring.get("instructions", "Watch for any unusual activity.")
        history_text = self._format_history(history)

        system_prompt = _SYSTEM_TEMPLATE.format(
            instructions=instructions.strip(),
            history=history_text,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": "Analyze this frame."},
                    ],
                },
            ],
        )

        raw = response.choices[0].message.content.strip()
        return self._parse(raw)

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        if not history:
            return "No previous observations."
        lines = [
            f"[{h.get('timestamp', '?')}] {h.get('event_type', '?').upper()}: {h.get('message', '')}"
            for h in history
        ]
        return "\n".join(lines)

    @staticmethod
    def _parse(raw: str) -> dict:
        # Strip accidental markdown fences
        cleaned = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", raw, flags=re.DOTALL).strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fall back: treat raw text as a comment
            result = {"type": "comment", "message": raw[:300], "tags": []}

        # Sanitise fields
        event_type = result.get("type", "ignore")
        if event_type not in ("ignore", "comment", "alert"):
            event_type = "comment"
        return {
            "type": event_type,
            "message": str(result.get("message", "")).strip(),
            "tags": result.get("tags", []) if isinstance(result.get("tags"), list) else [],
        }
