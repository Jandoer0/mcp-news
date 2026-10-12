"""Тест ИИ-агента: роль провайдера мокается на границе agent/provider —
без реальной Ollama и без зависимости от HTTP-стека (respx/httpx)."""
from unittest.mock import patch

from mcp_news.db import add_source, add_topic, get_tagged_total, save_posts
from mcp_news.topics import agent


def _result(content: str):
    from mcp_news.topics.provider import ProviderCallResult

    return ProviderCallResult(
        ok=True, content=content,
        provider_name="classifier", model="mock", url="mock", error=None,
    )


def test_agent_tags_relevant_posts():
    # Модель отвечает: релевантны посты 1 и 2 (мок на уровне call_role).
    with patch(
        "mcp_news.topics.agent.call_role",
        return_value=_result('{"matches": [1, 2]}'),
    ):
        src = add_source("telegram", "c1")
        save_posts(
            src["id"],
            [
                {"ext_id": "1", "text": "Лада Гранта вышла", "date": "2026-01-01", "url": "u1"},
                {"ext_id": "2", "text": "Про Ладу пишут", "date": "2026-01-02", "url": "u2"},
                {"ext_id": "3", "text": "Совсем другое", "date": "2026-01-03", "url": "u3"},
            ],
        )
        topic = add_topic("Машины", "Лада", 1440, "описание")

        res = agent.run_topic_agent(topic_id=topic["id"], max_batches=5)
    assert res["scanned"] == 3
    assert res["added"] == 2  # только 1 и 2
    assert get_tagged_total(topic["id"]) == 2


def test_agent_no_response_keeps_watermark():
    # Модель недоступна — прогон прерывается, посты не теряются.
    with patch(
        "mcp_news.topics.agent.call_role",
        return_value=_result(""),
    ):
        src = add_source("telegram", "c2")
        save_posts(src["id"], [{"ext_id": "9", "text": "x", "date": "2026-01-01", "url": "u"}])
        topic = add_topic("Т2", "тег", 1440, "")

        res = agent.run_topic_agent(topic_id=topic["id"], max_batches=1)
    # Прогон прерывается без ответа модели; посты не потеряны и не отобраны.
    assert res["added"] == 0
    assert get_tagged_total(topic["id"]) == 0
