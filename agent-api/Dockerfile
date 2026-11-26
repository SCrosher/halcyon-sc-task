FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Pinned dependencies first, in their own layer, so code changes don't reinstall them.
# requirements.txt is generated from pyproject.toml by `npm run lock`.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --no-deps . \
    && useradd --system --uid 10001 --no-create-home app

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
