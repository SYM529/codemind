from auth import create_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("Test123456")
    assert hashed != "Test123456"
    assert hashed.startswith("$2")
    assert verify_password("Test123456", hashed)
    assert not verify_password("wrong", hashed)


def test_create_token_contains_claims():
    import jwt
    from config import JWT_SECRET

    token = create_token({"id": 7, "username": "alice", "role": "admin"})
    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    assert payload["id"] == 7
    assert payload["username"] == "alice"
    assert payload["role"] == "admin"
    assert "exp" in payload
