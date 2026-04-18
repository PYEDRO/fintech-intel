import logging
import math
from typing import Optional, Literal
from fastapi import APIRouter, Query
from app.db import get_db
from app.models.schemas import TransactionListResponse, Transaction
from app.repositories.transaction_repository import TransactionRepository

router = APIRouter(prefix="/api", tags=["transactions"])
logger = logging.getLogger(__name__)

ALLOWED_SORT = {"id", "valor", "data", "status", "cliente", "categoria"}


@router.get("/transactions", response_model=TransactionListResponse)
def list_transactions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    cliente: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    sort_by: str = Query("data", pattern=f"^({'|'.join(ALLOWED_SORT)})$"),
    sort_order: Literal["asc", "desc"] = Query("desc"),
) -> TransactionListResponse:
    clauses, params = [], []

    if status:
        clauses.append("status = ?")
        params.append(status.lower())
    if cliente:
        clauses.append("cliente = ?")
        params.append(cliente)
    if search:
        clauses.append("(descricao LIKE ? OR id LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if start_date:
        clauses.append("data >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("data <= ?")
        params.append(end_date)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    offset = (page - 1) * per_page

    with get_db() as conn:
        repo = TransactionRepository(conn)
        rows, total = repo.list_paginated(
            where=where,
            params=params,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=per_page,
            offset=offset,
        )

    items = [Transaction(**r) for r in rows]
    pages = max(1, math.ceil(total / per_page))
    return TransactionListResponse(items=items, total=total, page=page, pages=pages)
