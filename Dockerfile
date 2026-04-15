FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY probes/ probes/

# templates 已包含在 src/report/templates/ 中，通过 package-data 打包
RUN pip install --no-cache-dir .

ENTRYPOINT ["fingerprint"]
