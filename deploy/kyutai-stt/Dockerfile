# Kyutai STT (open source, streaming, ~0.5 s delay) served by moshi-server on an NVIDIA GPU.
# Attendee streams each participant's audio here instead of relying on Meet captions.
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates build-essential pkg-config libssl-dev cmake git python3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
# No GPU is visible during `docker build`, so the kernels' target (Ampere, sm_86) is named here.
ENV PATH=/root/.cargo/bin:$PATH CUDA_COMPUTE_CAP=86
RUN cargo install --locked --features cuda moshi-server

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libssl3 libpython3.10 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /root/.cargo/bin/moshi-server /usr/local/bin/moshi-server
WORKDIR /app
COPY stt.toml /app/stt.toml
RUN mkdir -p /app/static
# Model weights download from Hugging Face on first start; mount /hf to keep them.
ENV HF_HOME=/hf
EXPOSE 8080
CMD ["moshi-server", "worker", "--config", "/app/stt.toml", "--port", "8080"]
