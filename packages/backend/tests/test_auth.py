"""Token verification, offline: a local ES256 pair stands in for Supabase's.

The JWKS client is monkeypatched to hand back our own public key, so every path
through `verify_token` runs without network — including the ones that must fail.
The failure tests matter more than the success one: each names a forgery this
endpoint would otherwise accept.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from fastapi import HTTPException

from core import auth

PRIVATE_KEY = generate_private_key(SECP256R1())
PUBLIC_KEY = PRIVATE_KEY.public_key()

OTHER_KEY = generate_private_key(SECP256R1())

USER = "11111111-2222-3333-4444-555555555555"


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJWKClient:
    def get_signing_key_from_jwt(self, token):
        return FakeSigningKey(PUBLIC_KEY)


@pytest.fixture(autouse=True)
def local_jwks(monkeypatch):
    monkeypatch.setattr(auth, "_jwk_client", lambda: FakeJWKClient())


def token(sub=USER, aud="authenticated", exp_offset=3600, key=PRIVATE_KEY, **extra):
    claims = {"sub": sub, "aud": aud, "exp": int(time.time()) + exp_offset,
              "role": "authenticated", **extra}
    return jwt.encode(claims, key, algorithm="ES256")


def test_a_valid_token_yields_its_user_id():
    assert auth.verify_token(token()) == USER


def test_an_expired_token_is_refused_with_a_reason():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(token(exp_offset=-3600))
    assert exc.value.status_code == 401
    assert exc.value.detail == "token expired"


def test_an_anon_token_does_not_open_a_tax_case():
    """Supabase's anon tokens carry the same signature and a different audience.

    This is the forgery that needs no forging: every visitor of the site holds one.
    """
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(token(aud="anon"))
    assert exc.value.status_code == 401


def test_a_token_signed_with_another_key_is_refused():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(token(key=OTHER_KEY))
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid token", "the reason is logged, not disclosed"


def test_a_token_without_a_subject_is_refused():
    claims = {"aud": "authenticated", "exp": int(time.time()) + 3600}
    bad = jwt.encode(claims, PRIVATE_KEY, algorithm="ES256")
    with pytest.raises(HTTPException):
        auth.verify_token(bad)


def test_garbage_is_refused_not_crashed_on():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token("not-a-token-at-all")
    assert exc.value.status_code == 401


def test_the_none_algorithm_is_not_accepted():
    """The classic downgrade: alg=none, no signature. Refused because the allowed
    algorithms are pinned, not read from the token."""
    unsigned = jwt.encode({"sub": USER, "aud": "authenticated",
                           "exp": int(time.time()) + 3600},
                          None, algorithm="none")
    with pytest.raises(HTTPException):
        auth.verify_token(unsigned)


def test_the_dependency_requires_a_bearer_header():
    import asyncio

    class FakeRequest:
        headers = {}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.current_user(FakeRequest()))
    assert exc.value.status_code == 401
    assert "bearer" in exc.value.detail
