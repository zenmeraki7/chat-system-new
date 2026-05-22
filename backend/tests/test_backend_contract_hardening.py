from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_connect_request_does_not_accept_frontend_asset_ids() -> None:
    text = _read("app/schemas/business.py")
    assert "class MetaOAuthCallbackRequest" in text
    assert "waba_id" not in text.split("class MetaOAuthCallbackRequest", 1)[1].split("class ", 1)[0]
    assert "phone_number_id" not in text.split("class MetaOAuthCallbackRequest", 1)[1].split("class ", 1)[0]


def test_template_status_mutation_route_removed() -> None:
    text = _read("app/api/v1/templates.py")
    assert '@router.patch("/{template_id}/status"' not in text
    assert "TemplateStatusUpdateRequest" not in text


def test_contacts_contracts_present() -> None:
    text = _read("app/api/v1/contacts.py")
    assert '@router.post("/bulk-suppress/preview"' in text
    assert '@router.post("/bulk-suppress/confirm"' in text
    assert '@router.post("/bulk-tag"' in text
    assert '@router.get("/exports/{job_id}/download-token"' in text
    assert '@router.get("/exports/download/{token}")' in text


def test_conversation_assignment_contracts_present() -> None:
    schema = _read("app/schemas/conversation.py")
    assert "assignee_public_id" in schema
    assert "assigned_user_id: uuid.UUID | None = None" not in schema
    api = _read("app/api/v1/conversations.py")
    assert 'detail="assignee_public_id or assigned_team_id is required"' in api
    assert '@router.get("/team/members"' in api


def test_canonical_api_error_handlers_present() -> None:
    main = _read("app/main.py")
    assert "@app.exception_handler(HTTPException)" in main
    assert "@app.exception_handler(RequestValidationError)" in main
    assert "@app.exception_handler(Exception)" in main


def test_signed_download_helpers_present() -> None:
    storage = _read("app/services/object_storage_service.py")
    assert "def build_signed_download_url" in storage
    assert "def resolve_signed_download_token" in storage
