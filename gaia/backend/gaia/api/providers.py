from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gaia.core import secrets
from gaia.db.session import get_session
from gaia.llm.base import ProviderError
from gaia.llm.registry import (
    PROVIDER_CLASSES,
    available_provider_ids,
    build_provider,
    describe_providers,
)
from gaia.schemas.api import ModelOut, ProviderCredentialIn, ProviderOut
from gaia.services import settings_service

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("", response_model=list[ProviderOut])
def list_providers(session: Session = Depends(get_session)) -> list[ProviderOut]:
    result = []
    for described in describe_providers():
        provider_settings = settings_service.get_provider_settings(session, described["id"])
        key = (
            secrets.describe_key(described["id"])
            if described["requires_api_key"]
            else {"configured": True, "hint": None, "source": None}
        )
        result.append(
            ProviderOut(
                **described,
                configured=bool(key["configured"]),
                key_hint=key["hint"],
                key_source=key["source"],
                base_url=provider_settings.get("base_url"),
                default_model=provider_settings.get("default_model"),
            )
        )
    return result


@router.put("/{provider_id}/credentials", response_model=ProviderOut)
def set_credentials(
    provider_id: str,
    payload: ProviderCredentialIn,
    session: Session = Depends(get_session),
) -> ProviderOut:
    """Store a provider's API key and endpoint settings.

    The key goes to the OS keyring (or an owner-only file) — never to the
    database — and is never echoed back in the response.
    """
    _require_known(provider_id)
    if payload.api_key:
        secrets.set_api_key(provider_id, payload.api_key.strip())
    settings_service.set_provider_settings(
        session,
        provider_id,
        {"base_url": payload.base_url, "default_model": payload.default_model},
    )
    session.commit()
    return next(p for p in list_providers(session) if p.id == provider_id)


@router.delete("/{provider_id}/credentials", response_model=ProviderOut)
def clear_credentials(provider_id: str, session: Session = Depends(get_session)) -> ProviderOut:
    _require_known(provider_id)
    secrets.delete_api_key(provider_id)
    return next(p for p in list_providers(session) if p.id == provider_id)


@router.get("/{provider_id}/models", response_model=list[ModelOut])
async def list_models(provider_id: str, session: Session = Depends(get_session)) -> list[ModelOut]:
    _require_known(provider_id)
    provider = build_provider(session, provider_id)
    try:
        models = await provider.list_models()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    return [ModelOut(**m.to_dict()) for m in models]


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str, session: Session = Depends(get_session)) -> dict:
    """Used by the first-run wizard and Settings to verify a connection."""
    _require_known(provider_id)
    provider = build_provider(session, provider_id)
    health = await provider.health()
    return health.to_dict()


def _require_known(provider_id: str) -> None:
    if provider_id not in PROVIDER_CLASSES or provider_id not in available_provider_ids():
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
