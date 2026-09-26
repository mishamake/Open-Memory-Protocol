# Test image: Python for the adapter and mappings, Node for the ctx reference implementation.
# Build from prototypes/ so the sibling prototypes the mappings import are in the context:
#   docker build -f contextnest-draft-adapter/Dockerfile -t nest-adapter .
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @promptowl/contextnest-cli@2.8.0 \
    && pip install --no-cache-dir uv
WORKDIR /prototypes
COPY python-loader-validator ./python-loader-validator
COPY packer-draft-langchain-harness ./packer-draft-langchain-harness
COPY ibm-draft-memory-records ./ibm-draft-memory-records
COPY aidp-draft-fmp ./aidp-draft-fmp
COPY contextnest-draft-adapter/pyproject.toml contextnest-draft-adapter/README.md ./contextnest-draft-adapter/
COPY contextnest-draft-adapter/contextnest_adapter ./contextnest-draft-adapter/contextnest_adapter
COPY contextnest-draft-adapter/mappings ./contextnest-draft-adapter/mappings
COPY contextnest-draft-adapter/fixtures ./contextnest-draft-adapter/fixtures
COPY contextnest-draft-adapter/tests ./contextnest-draft-adapter/tests
COPY contextnest-draft-adapter/examples ./contextnest-draft-adapter/examples
WORKDIR /prototypes/contextnest-draft-adapter
RUN uv venv && uv pip install \
      -e ../python-loader-validator \
      -e ../ibm-draft-memory-records \
      -e ../aidp-draft-fmp \
      -e ".[dev,mappings]"
ENV PATH="/prototypes/contextnest-draft-adapter/.venv/bin:$PATH"
CMD ["pytest", "-q", "-rs"]
