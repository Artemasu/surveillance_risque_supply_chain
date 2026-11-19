# Une seule image pour l'API et l'interface : docker-compose choisit la commande.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
    # Modèle spaCy multilingue. S'il ne se télécharge pas, l'agent médias tourne sur les référentiels seuls.
    && (python -m spacy download xx_ent_wiki_sm || echo "modèle spaCy indisponible : repli sur les référentiels")

COPY . .

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000 8501
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
