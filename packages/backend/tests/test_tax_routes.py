import pytest


def test_health_check(client):
    response = client.get("/api/v1/tax/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ask_tax_question_invalid_request(client):
    response = client.post(
        "/api/v1/tax/ask",
        json={"text": ""},  # Empty text should fail validation
    )
    assert response.status_code == 422


def test_ask_tax_question_valid_request(client, fake_llm, sample_tax_question):
    response = client.post(
        "/api/v1/tax/ask",
        json=sample_tax_question,
    )
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "explanation" in data
    assert "sources" in data
    # advanced-RAG fields
    assert data["intent"] == "knowledge"
    assert isinstance(data["warnings"], list)    # dynamic warnings only (disclaimer is static UI)
    assert data["usage"]["total_tokens"] > 0
    # two LLM calls: query analysis + generation
    assert len(fake_llm.calls) == 2
    # cited source surfaced in the sources list
    assert data["sources"][0]["source_id"] == "lsth-2022-anhang-14-entfernungspauschalen"


# --- request id + feedback ---

def test_every_response_carries_a_request_id(client, sample_tax_question):
    response = client.post("/api/v1/tax/ask", json=sample_tax_question)
    assert response.headers["X-Request-ID"]
    # the body id matches the header, which is what makes the 👍/👎 joinable
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_a_client_supplied_request_id_is_echoed_when_it_is_an_identifier(client, sample_tax_question):
    response = client.post("/api/v1/tax/ask", json=sample_tax_question,
                           headers={"X-Request-ID": "trace-abc_123"})
    assert response.headers["X-Request-ID"] == "trace-abc_123"


def test_a_junk_request_id_is_replaced_rather_than_logged(client, sample_tax_question):
    """The id lands in every log line for the request, so it must stay an identifier."""
    response = client.post("/api/v1/tax/ask", json=sample_tax_question,
                           headers={"X-Request-ID": 'evil" injected=1\nnewline'})
    assert response.headers["X-Request-ID"].isalnum()


def test_feedback_is_accepted(client):
    response = client.post("/api/v1/tax/feedback",
                           json={"request_id": "abc123", "rating": "up"})
    assert response.status_code == 200
    assert response.json()["status"] == "recorded"


def test_feedback_rejects_an_unknown_rating(client):
    response = client.post("/api/v1/tax/feedback",
                           json={"request_id": "abc123", "rating": "sideways"})
    assert response.status_code == 422
