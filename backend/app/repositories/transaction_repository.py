"""
Repository pattern: encapsulates all SQL access to the transacoes table.
Services depend on this interface — never on sqlite3 directly.
This makes unit testing trivial (mock the repo, not the DB connection).
"""
import sqlite3
import pandas as pd
from typing import Optional


class TransactionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Write operations ──────────────────────────────────────────────────────

    def replace_all(self, df: pd.DataFrame) -> int:
        """Replace every row with a new DataFrame (bulk upload)."""
        self._conn.execute("DELETE FROM transacoes")
        df[["id", "valor", "data", "status", "cliente", "descricao", "categoria"]].to_sql(
            "transacoes", self._conn, if_exists="append", index=False
        )
        return len(df)

    def update_category(self, txn_id: str, category: str) -> None:
        self._conn.execute(
            "UPDATE transacoes SET categoria = ? WHERE id = ?", (category, txn_id)
        )

    # ── Read operations ───────────────────────────────────────────────────────

    def count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM transacoes"
        ).fetchone()["cnt"]

    def get_all_raw(self) -> list[dict]:
        """Full table scan — used by anomaly detection and RAG index rebuild."""
        rows = self._conn.execute(
            "SELECT id, valor, status, cliente, descricao, data, categoria FROM transacoes"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_top_by_value(self, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            """SELECT id, cliente, valor, status, descricao
               FROM transacoes ORDER BY valor DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats_by_client(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT cliente,
                      COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita,
                      COALESCE(SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END), 0) AS atrasadas,
                      COALESCE(AVG(valor), 0) AS ticket_medio
               FROM transacoes GROUP BY cliente"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_aggregates(
        self,
        where: str = "",
        params: Optional[list] = None,
    ) -> dict:
        params = params or []
        row = self._conn.execute(
            f"""SELECT
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita_total,
                COALESCE(AVG(CASE WHEN status='pago' THEN valor END), 0)          AS ticket_medio,
                COUNT(*)                                                           AS total_transacoes,
                COALESCE(SUM(CASE WHEN status='pago'     THEN 1 ELSE 0 END), 0)   AS pagas,
                COALESCE(SUM(CASE WHEN status='pendente' THEN 1 ELSE 0 END), 0)   AS pendentes,
                COALESCE(SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END), 0)   AS atrasadas
            FROM transacoes {where}""",
            params,
        ).fetchone()
        return dict(row)

    def get_monthly_evolution(self, where: str = "", params: Optional[list] = None) -> list[dict]:
        params = params or []
        rows = self._conn.execute(
            f"""SELECT strftime('%Y-%m', data) AS mes,
                       COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita,
                       COUNT(*) AS count
                FROM transacoes {where}
                GROUP BY mes ORDER BY mes""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_client(self, where: str = "", params: Optional[list] = None) -> list[dict]:
        params = params or []
        rows = self._conn.execute(
            f"""SELECT cliente,
                       COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita,
                       COUNT(*) AS count
                FROM transacoes {where}
                GROUP BY cliente ORDER BY receita DESC""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_category(self, where: str = "", params: Optional[list] = None) -> list[dict]:
        params = params or []
        rows = self._conn.execute(
            f"""SELECT COALESCE(categoria, 'Não Classificado') AS categoria,
                       COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita,
                       COUNT(*) AS count
                FROM transacoes {where}
                GROUP BY categoria ORDER BY receita DESC""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_n_months_revenue(self, n: int = 6, where: str = "", params: Optional[list] = None) -> list[dict]:
        params = params or []
        rows = self._conn.execute(
            f"""SELECT strftime('%Y-%m', data) AS mes,
                       SUM(CASE WHEN status='pago' THEN valor ELSE 0 END) AS receita
                FROM transacoes {where}
                GROUP BY mes ORDER BY mes DESC LIMIT ?""",
            params + [n],
        ).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def list_paginated(
        self,
        where: str = "",
        params: Optional[list] = None,
        sort_by: str = "data",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        params = params or []
        order = f"ORDER BY {sort_by} {sort_order.upper()}"
        total = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM transacoes {where}", params
        ).fetchone()["cnt"]
        rows = self._conn.execute(
            f"SELECT * FROM transacoes {where} {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
