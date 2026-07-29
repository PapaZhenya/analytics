import uuid

from backend.app.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify_roundtrip():
    password = "correct horse battery staple"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong password", hashed)


def test_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)

    payload = decode_token(token, expected_type=TokenType.access)

    assert payload is not None
    assert payload.user_id == user_id
    assert payload.token_type == TokenType.access


def test_access_token_rejected_as_refresh():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)

    # An access token must not be usable where a refresh token is expected — the type
    # claim is what /auth/refresh checks to reject a stolen/misused access token.
    assert decode_token(token, expected_type=TokenType.refresh) is None


def test_refresh_token_roundtrip_and_jti():
    user_id = uuid.uuid4()
    token, jti, expires_at = create_refresh_token(user_id)

    payload = decode_token(token, expected_type=TokenType.refresh)

    assert payload is not None
    assert payload.user_id == user_id
    assert payload.jti == jti


def test_garbage_token_rejected():
    assert decode_token("not-a-real-token", expected_type=TokenType.access) is None
