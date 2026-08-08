import os
from typing import Optional


def call_llm(prompt: str, provider: str = "openai") -> Optional[str]:
    """Call configured LLM provider. Currently supports OpenAI if OPENAI_API_KEY is set.

    Returns text or None if no API configured.
    """
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            import openai
            openai.api_key = api_key
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return None
    return None
