from src.services.cost import estimate_gemini_cost, estimate_llm_cost, estimate_whisper_cost


def test_whisper_cost_one_minute():
    cost = estimate_whisper_cost(60.0)
    assert abs(cost - 0.006) < 0.0001


def test_whisper_cost_ten_minutes():
    cost = estimate_whisper_cost(600.0)
    assert abs(cost - 0.06) < 0.001


def test_gemini_cost():
    # 60 seconds = 1920 input tokens
    cost = estimate_gemini_cost(60.0, output_tokens=500, model="gemini-3.1-flash-lite-preview")
    assert cost > 0
    assert cost < 0.01


def test_llm_cost_openai():
    cost = estimate_llm_cost(1000, 500, "gpt-5.4", "openai")
    assert cost > 0


def test_llm_cost_gemini():
    cost = estimate_llm_cost(1000, 500, "gemini-3.1-flash-lite-preview", "gemini")
    assert cost > 0
