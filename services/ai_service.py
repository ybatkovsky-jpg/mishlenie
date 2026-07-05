"""DeepSeek API client wrapper — manages chat and reasoner model calls."""

import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger(__name__)

# Conversation window size (messages sent as context to AI)
MAX_CONTEXT_MESSAGES = 20

# Rough word limit for bot responses
MAX_WORDS_RESPONSE = 450  # Slightly higher than 400 to allow for formatting chars


class AIService:
    """Manages communication with DeepSeek API."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Send messages to DeepSeek and get the full response.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            model: Model name (defaults to deepseek-chat).
            temperature: Creativity level.
            max_tokens: Maximum tokens in the response.
        """
        model = model or settings.deepseek_chat_model
        logger.info("Sending request to DeepSeek model=%s messages_count=%d", model, len(messages))

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content or ""
        content = self._clean_markdown(content)
        logger.info("Received response from DeepSeek, length=%d chars", len(content))
        return content

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Stream response from DeepSeek, yielding text chunks."""
        model = model or settings.deepseek_chat_model

        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def get_diagnostic_question(
        self,
        sphere: str,
        thinking_type: str,
        question_number: int,
        previous_answers: list[str] | None = None,
    ) -> str:
        """Get a single diagnostic question for a specific thinking type.

        Used in Phase 1 — each question is a mini-scenario from the user's sphere.
        """
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import DIAGNOSTIC_INTRO, DIAGNOSTIC_NEXT_QUESTION, get_thinking_type_name

        type_name = get_thinking_type_name(thinking_type)

        if question_number == 1:
            user_msg = DIAGNOSTIC_INTRO.format(sphere=sphere)
        else:
            prev = "\n".join(f"Q{i+1}: {a}" for i, a in enumerate(previous_answers or []))
            user_msg = DIAGNOSTIC_NEXT_QUESTION.format(
                thinking_type=type_name,
                question_number=question_number,
            )
            user_msg += f"\n\nПредыдущие ответы пользователя:\n{prev}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": user_msg},
        ]

        return await self.chat(messages, temperature=0.8, max_tokens=1024)

    def build_profile_prompt(
        self, answers: list[str], sphere: str
    ) -> list[dict[str, str]]:
        """Build messages for generating the thinking profile after diagnostics."""
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import DIAGNOSTIC_PROFILE

        ans = "\n".join(f"Q{i+1} ({t}): {a}" for i, (a, t) in enumerate(
            zip(answers, ["аналитическое", "логическое", "критическое", "системное", "стратегическое", "креативное", "эмоциональный интеллект"])
        ))

        return [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": DIAGNOSTIC_PROFILE.format(answers=ans, sphere=sphere)},
        ]

    async def get_training_task(
        self,
        thinking_type: str,
        sphere: str,
        difficulty: int = 0,
        use_reasoner: bool = False,
    ) -> str:
        """Generate a training task for a specific thinking type (Phase 2)."""
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import TRAINING_TASK, get_difficulty_label, get_thinking_type_name

        type_name = get_thinking_type_name(thinking_type)
        diff_label = get_difficulty_label(difficulty)

        user_msg = TRAINING_TASK.format(
            thinking_type=type_name,
            sphere=sphere,
            difficulty=diff_label,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": user_msg},
        ]

        model = settings.deepseek_reasoner_model if use_reasoner else settings.deepseek_chat_model
        return await self.chat(messages, model=model, temperature=0.8, max_tokens=2048)

    async def get_feedback(
        self,
        thinking_type: str,
        task: str,
        answer: str,
        use_reasoner: bool = False,
    ) -> str:
        """Get AI feedback on user's answer (Phase 3)."""
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import FEEDBACK_REQUEST, get_thinking_type_name

        type_name = get_thinking_type_name(thinking_type)
        user_msg = FEEDBACK_REQUEST.format(
            thinking_type=type_name,
            task=task[:1500],
            answer=answer[:2000],
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": user_msg},
        ]

        model = settings.deepseek_reasoner_model if use_reasoner else settings.deepseek_chat_model
        return await self.chat(messages, model=model, temperature=0.6, max_tokens=2048)

    async def get_combined_task(
        self,
        completed_types: list[str],
        sphere: str,
    ) -> str:
        """Generate a combined task using 2-3 thinking types (Phase 4). Always uses reasoner."""
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import COMBINED_TASK, get_thinking_type_name

        types_str = ", ".join(get_thinking_type_name(t) for t in completed_types)
        user_msg = COMBINED_TASK.format(
            completed_types=types_str,
            sphere=sphere,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": user_msg},
        ]

        # Always use reasoner for combined tasks
        return await self.chat(
            messages,
            model=settings.deepseek_reasoner_model,
            temperature=0.8,
            max_tokens=2048,
        )

    async def get_mindfulness_exercise(self) -> str:
        """Get a mindfulness exercise for Phase 5."""
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import MINDFULNESS_INTEGRATION

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": MINDFULNESS_INTEGRATION},
        ]

        return await self.chat(messages, temperature=0.7, max_tokens=1024)

    async def get_profile_update(
        self,
        current_profile: dict[str, int],
        thinking_type: str,
        score: int,
        total_completed: int,
        types_completed: int,
        streak: int = 0,
    ) -> str:
        """Get updated thinking profile display."""
        from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
        from prompts.templates import PROFILE_UPDATE, get_thinking_type_name

        profile_str = "\n".join(
            f"{get_thinking_type_name(k)}: {v}/10" for k, v in current_profile.items()
        )
        type_name = get_thinking_type_name(thinking_type)

        user_msg = PROFILE_UPDATE.format(
            current_profile=profile_str,
            thinking_type=type_name,
            score=score,
        )
        user_msg += f"\n\nСтатистика: заданий выполнено: {total_completed}, видов пройдено: {types_completed}"
        if streak >= 3:
            user_msg += f"\n🔥 Серия: {streak} заданий подряд с высокой оценкой!"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": user_msg},
        ]

        return await self.chat(messages, temperature=0.6, max_tokens=1024)

    @staticmethod
    def estimate_words(text: str) -> int:
        """Rough word count for Russian text."""
        return len(text.split())

    @staticmethod
    def _clean_markdown(text: str) -> str:
        """Remove Markdown formatting that Telegram HTML mode can't render."""
        # Remove ### headers (keep the text)
        text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
        # Remove **bold** → bold
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        # Remove __underline__
        text = re.sub(r'__(.+?)__', r'\1', text)
        return text


# Singleton
ai_service = AIService()
