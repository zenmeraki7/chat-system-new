from app.utils.cursor import decode_cursor, encode_cursor, stable_filters_hash, InvalidCursorError


def test_cursor_roundtrip_and_signature_validation():
    payload = {
        "sortKey": "updated_at",
        "sortDir": "desc",
        "sortValue": "2026-05-21T10:00:00+00:00",
        "id": "4a28c1a4-dc8d-4c1c-a810-0e9f215aab11",
        "filtersHash": "abc123",
    }
    token = encode_cursor(payload)
    decoded = decode_cursor(token)
    assert decoded == payload


def test_cursor_tamper_detected():
    payload = {
        "sortKey": "updated_at",
        "sortDir": "desc",
        "sortValue": "2026-05-21T10:00:00+00:00",
        "id": "4a28c1a4-dc8d-4c1c-a810-0e9f215aab11",
        "filtersHash": "abc123",
    }
    token = encode_cursor(payload)
    # Force tamper by changing one character in the token.
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    try:
        decode_cursor(tampered)
        assert False, "expected InvalidCursorError"
    except InvalidCursorError:
        assert True


def test_stable_filters_hash_is_order_independent():
    a = {"search": "john", "tag": "vip", "suppressed": False}
    b = {"suppressed": False, "tag": "vip", "search": "john"}
    assert stable_filters_hash(a) == stable_filters_hash(b)
