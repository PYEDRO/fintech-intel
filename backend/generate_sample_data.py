"""
Generate sample XLSX with ~1000 financial transactions for demo purposes.
Usage: python generate_sample_data.py
Output: data/transacoes_sample.xlsx
"""
import random
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

CLIENTES = ["Startup X", "Loja Y", "Empresa A", "Empresa B", "Empresa C", "Empresa D"]
STATUS = ["pago", "pendente", "atrasado"]
STATUS_WEIGHTS = [0.65, 0.20, 0.15]

DESCRICOES = [
    "Assinatura plataforma educacional",
    "Contratação de curso preparatório OAB",
    "Licença anual sistema de gestão",
    "Serviço avulso de consultoria",
    "Compra de material didático",
    "Plano premium de acesso ao conteúdo",
    "Cobrança recorrente mensal",
    "Renovação de licença software",
    "Treinamento corporativo - turma 1",
    "Mentoria individual OAB 1ª fase",
    "Pacote intensivo revisão constitucional",
    "Acesso vitalício ao curso",
    "Semestralidade plano estudante",
    "Cobrança por uso de API",
    "Taxa de implantação do sistema",
    "Suporte técnico especializado",
    "Consultoria em estruturação de provas",
    "Assinatura newsletter jurídica premium",
    "Módulo de simulados online",
    "Contratação pacote empresarial",
]


def random_date(start: datetime, end: datetime) -> str:
    delta = end - start
    random_days = random.randint(0, delta.days)
    return (start + timedelta(days=random_days)).strftime("%Y-%m-%d")


def generate(n: int = 1000) -> pd.DataFrame:
    start = datetime(2024, 1, 1)
    end = datetime(2025, 12, 31)

    rows = []
    for i in range(1, n + 1):
        cliente = random.choice(CLIENTES)
        valor = round(random.uniform(22, 4987), 2)
        # Large clients get slightly higher values
        if cliente in ("Empresa A", "Empresa B"):
            valor = round(random.uniform(500, 4987), 2)

        rows.append({
            "id": f"txn_{i:05d}",
            "valor": valor,
            "data": random_date(start, end),
            "status": random.choices(STATUS, STATUS_WEIGHTS)[0],
            "cliente": cliente,
            "descricao": random.choice(DESCRICOES),
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    df = generate(1000)
    output = "data/transacoes_sample.xlsx"
    df.to_excel(output, index=False)
    print(f"✅ {len(df)} transações geradas em {output}")
    print(df["status"].value_counts().to_string())
    print(f"Valor total pago: R$ {df[df['status']=='pago']['valor'].sum():,.2f}")
