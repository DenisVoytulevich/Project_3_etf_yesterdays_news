"""Проверка OpenAI: ключ и модель из .env."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from src.config import Settings


def main() -> int:
    print("=" * 50)
    print("Проверка OpenAI")
    print("=" * 50)

    try:
        settings = Settings()
    except Exception as e:
        print(f"[FAIL] .env: {e}")
        return 1

    if not settings.openai_api_key or settings.openai_api_key == "your_openai_key":
        print("[FAIL] OPENAI_API_KEY не задан в .env")
        return 1
    print("[OK]  OPENAI_API_KEY задан")

    model = settings.openai_model.strip()
    if not model:
        print("[FAIL] OPENAI_MODEL пустой")
        return 1
    print(f"[OK]  OPENAI_MODEL: {model}")

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Ответь одним словом: OK"}],
            max_completion_tokens=10,
        )
        answer = (response.choices[0].message.content or "").strip()
        used = response.model
        print(f"[OK]  API ответил: {answer!r}")
        print(f"[OK]  Фактическая модель: {used}")
    except Exception as e:
        print(f"[FAIL] Запрос к OpenAI: {e}")
        return 1

    print("=" * 50)
    print("Итог: OpenAI настроен, модель из .env работает")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
