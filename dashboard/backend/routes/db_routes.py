"""Database routes: paper counts, coverage drilldown."""
from fastapi import APIRouter, Depends
from auth import require_viewer, TokenPayload
import db_reader

router = APIRouter()


@router.get("/counts")
async def get_counts(_user: TokenPayload = Depends(require_viewer)):
    return db_reader.get_paper_counts()


@router.get("/coverage/drilldown")
async def drilldown(keyword: str, year: int, _user: TokenPayload = Depends(require_viewer)):
    return db_reader.get_drilldown(keyword, year)
