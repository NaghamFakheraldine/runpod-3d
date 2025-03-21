FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies with better error handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    git \
    wget \
    unzip \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    build-essential \
    ffmpeg \
    libavcodec-extra \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && which ffmpeg || (echo "FFmpeg not found" && exit 1)

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install NumPy first
RUN pip install --no-cache-dir numpy==1.24.3

# Create workspace directory
WORKDIR /workspace

# Clone ComfyUI repo
RUN git clone https://github.com/comfyanonymous/ComfyUI

# Install PyTorch and related packages with specific CUDA versions
RUN pip install --no-cache-dir \
    torch==2.1.2 \
    torchvision==0.16.2 \
    --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu121

# Install FFmpeg-related packages
RUN pip install --no-cache-dir imageio-ffmpeg==0.4.9

# Create all required directories BEFORE installing dependencies
RUN mkdir -p /workspace/ComfyUI/models/checkpoints \
    /workspace/ComfyUI/output \
    /workspace/ComfyUI/custom_nodes

# Install ComfyUI requirements
WORKDIR /workspace/ComfyUI
RUN pip install --no-cache-dir -r requirements.txt

# Install additional requirements
RUN pip install --no-cache-dir runpod boto3 requests huggingface_hub pillow

# Install custom nodes with error handling and proper cleanup to save space
RUN cd /workspace/ComfyUI/custom_nodes && \
    # Clone VideoHelperSuite
    rm -rf ComfyUI-VideoHelperSuite && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    cd ComfyUI-VideoHelperSuite && \
    pip install -r requirements.txt || echo "Failed to install VideoHelperSuite requirements, continuing anyway" && \
    cd .. && \
    # Clone Frame Interpolation
    rm -rf ComfyUI-Frame-Interpolation && \
    git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git && \
    cd ComfyUI-Frame-Interpolation && \
    pip install -r requirements.txt || echo "Failed to install Frame Interpolation requirements, continuing anyway" && \
    cd .. && \
    # Clone Tooling Nodes
    rm -rf comfyui-tooling-nodes && \
    git clone https://github.com/Acly/comfyui-tooling-nodes

# Clean up git repos to save space
RUN find /workspace -name ".git" -type d -exec rm -rf {} + 2>/dev/null || true

# Clean pip cache to save space
RUN pip cache purge

# Return to workspace directory
WORKDIR /workspace

# Copy scripts after all the heavy installations
COPY handler.py /workspace/
COPY start.sh /workspace/
RUN chmod +x /workspace/start.sh

# Copy workflow.json
COPY workflow.json /workspace/

# Check and fix the start.sh file if needed
RUN bash -n /workspace/start.sh || echo "Warning: start.sh has syntax errors that need to be fixed"

ENTRYPOINT ["/bin/bash", "/workspace/start.sh"]