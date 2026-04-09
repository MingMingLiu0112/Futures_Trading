# ============================================================
# VeighNa (vnpy) Docker Image - Full Build with Web UI
# Base: Ubuntu 22.04 + Python 3.10
# ============================================================

FROM python:3.10-slim

LABEL maintainer="VeighNa Community"
LABEL description="VeighNa quantitative trading framework with Web UI support"

# Proxy configuration for build
ENV HTTP_PROXY=http://127.0.0.1:7890 \
    HTTPS_PROXY=http://127.0.0.1:7890 \
    http_proxy=http://127.0.0.1:7890 \
    https_proxy=http://127.0.0.1:7890 \
    all_proxy=socks5h://127.0.0.1:7890 \
    FTP_PROXY=http://127.0.0.1:7890 \
    ftp_proxy=http://127.0.0.1:7890

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    build-essential \
    cmake \
    libgl1-mesa-dev \
    libglib2.0-dev \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    locales \
    && locale-gen zh_CN.UTF-8 en_US.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build TA-Lib from source (required by vnpy)
RUN wget -q https://pip.vnpy.com/colletion/ta-lib-0.6.4-src.tar.gz \
    && tar -xzf ta-lib-0.6.4-src.tar.gz \
    && cd ta-lib-0.6.4 \
    && ./configure --prefix=/usr/local \
    && make -j$(nproc) \
    && make install \
    && ldconfig \
    && cd / \
    && rm -rf ta-lib-0.6.4*

# Clone vnpy source via proxy
ENV HTTP_PROXY=http://127.0.0.1:7890 \
    HTTPS_PROXY=http://127.0.0.1:7890 \
    http_proxy=http://127.0.0.1:7890 \
    https_proxy=http://127.0.0.1:7890

WORKDIR /app
RUN git clone --depth=1 --branch master https://github.com/vnpy/vnpy.git .

# Install Python build dependencies first
RUN pip install --upgrade pip wheel setuptools

# Install numpy before ta-lib python binding
RUN pip install numpy==2.2.3

# Install TA-Lib Python binding
RUN pip install ta-lib==0.6.4

# Install vnpy core from local source
RUN pip install .

# NOTE: alpha extras omitted (torch+cuda ~2.5GB) — uncomment if needed
# RUN pip install -e ".[alpha]"

# Install vnpy extension packages (gateways + apps)
# These are separate packages maintained by vnpy community
RUN pip install \
    vnpy_rpcservice \
    vnpy_sqlite \
    vnpy_mongodb \
    vnpy_mysql \
    vnpy_ctp \
    vnpy_ctastrategy \
    vnpy_datamanager \
    vnpy_ctabacktester \
    vnpy_chartwizard \
    vnpy_optionmaster \
    vnpy_portfoliostrategy \
    vnpy_spreadtrading \
    vnpy_excelrtd \
    vnpy_riskmanager \
    vnpy_scripttrader \
    "vnpy-paperaccount"

# Install Web UI related packages
RUN pip install \
    fastapi \
    uvicorn[standard] \
    flask \
    flask-cors \
    sqlalchemy \
    pymongo \
    pymysql \
    redis \
    apscheduler \
    pydantic \
    python-multipart

# Web API server (using Flask as example web layer on top of RPC service)
# This provides a REST API to interact with the vnpy RPC engine
RUN pip install \
    vnpy_rest \
    vnpy_websocket

# Clean pip cache (no-op since PIP_NO_CACHE_DIR=1)
# RUN pip cache purge

# Create non-root user for runtime
RUN useradd -m -s /bin/bash vnpy && \
    chown -R vnpy:vnpy /app

USER vnpy
WORKDIR /app

# Copy entrypoint script
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Expose RPC service ports
# 2014: REP (request-reply, synchronous)
# 4102: PUB (publish, asynchronous)
# 8765: Flask/HTTP web API (if using vnpy_restful)
# 8080: uvicorn default
EXPOSE 2014 4102 8765 8080

ENV VNPY_DATA_PATH=/app/data \
    VNPY_LOG_PATH=/app/logs

# Default: run the RPC service in daemon mode
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["rpc"]
