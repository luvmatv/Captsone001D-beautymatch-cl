# BeautyMatch CL API image (Azure Container Apps; see docs/deploy_azure.md).
#
#   docker build -t beautymatch-api:<git sha> .
#   docker run -p 8000:8000 -e DATABASE_URL=... -e API_CORS_ORIGINS=... beautymatch-api:<git sha>
#
# The embedding model is downloaded at build time and the container runs
# offline (HF_HUB_OFFLINE): a cold start never waits for Hugging Face, and
# GET /search/semantic answers 503 + Retry-After while the model loads (~20-30 s).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf

RUN useradd --create-home --uid 1000 app && mkdir -p /opt/hf && chown app:app /opt/hf
WORKDIR /app

COPY requirements-api.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 \
    && pip install -r requirements-api.txt

COPY src ./src
USER app
# intfloat/multilingual-e5-base into /opt/hf (the same model as the listings' embeddings)
RUN python -c "from src.matching.embeddings import load_model; load_model()"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
