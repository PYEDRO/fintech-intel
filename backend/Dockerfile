FROM python:3.11-slim

WORKDIR /app

# Deps mínimas de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Instala dependências sem cache para imagem menor
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download do modelo ONNX (fastembed, sem PyTorch)
# ~90MB, só ocorre no build — startup instantâneo em runtime
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2'); print('Model cached.')"

COPY . .
RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
