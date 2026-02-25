"""Markets API — list available Lighter markets."""

from fastapi import APIRouter, Depends

from backend.services.market_data import fetch_markets
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/markets", tags=["markets"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_markets():
    """List all available markets on Lighter."""
    markets = await fetch_markets()
    return markets
