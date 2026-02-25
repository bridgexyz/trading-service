"""CRUD API for Lighter DEX credentials."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.credential import Credential
from backend.schemas.credential import CredentialCreate, CredentialUpdate, CredentialRead
from backend.services.encryption import encrypt, decrypt
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/credentials", tags=["credentials"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[CredentialRead])
def list_credentials(session: Session = Depends(get_session)):
    return session.exec(select(Credential)).all()


@router.post("", response_model=CredentialRead, status_code=201)
def create_credential(
    data: CredentialCreate,
    session: Session = Depends(get_session),
):
    cred = Credential(
        name=data.name,
        lighter_host=data.lighter_host,
        api_key_index=data.api_key_index,
        private_key_encrypted=encrypt(data.private_key),
        account_index=data.account_index,
    )
    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


@router.get("/{cred_id}", response_model=CredentialRead)
def get_credential(cred_id: int, session: Session = Depends(get_session)):
    cred = session.get(Credential, cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    return cred


@router.put("/{cred_id}", response_model=CredentialRead)
def update_credential(
    cred_id: int,
    data: CredentialUpdate,
    session: Session = Depends(get_session),
):
    cred = session.get(Credential, cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    update_data = data.model_dump(exclude_unset=True)
    if "private_key" in update_data:
        pk = update_data.pop("private_key")
        if pk is not None:
            cred.private_key_encrypted = encrypt(pk)

    for key, value in update_data.items():
        setattr(cred, key, value)

    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


@router.delete("/{cred_id}", status_code=204)
def delete_credential(cred_id: int, session: Session = Depends(get_session)):
    cred = session.get(Credential, cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    session.delete(cred)
    session.commit()


@router.post("/{cred_id}/test")
async def test_credential(cred_id: int, session: Session = Depends(get_session)):
    """Test connectivity to Lighter using this credential."""
    cred = session.get(Credential, cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        pk = decrypt(cred.private_key_encrypted)
        from backend.services.lighter_client import LighterClient

        client = LighterClient(
            host=cred.lighter_host,
            private_key=pk,
            api_key_index=cred.api_key_index,
            account_index=cred.account_index,
        )
        result = await client.test_connection()
        await client.close()
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
