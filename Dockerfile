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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Create workspace directory
WORKDIR /workspace

# Clone ComfyUI repo
RUN git clone https://github.com/comfyanonymous/ComfyUI

# Install PyTorch first to avoid dependency conflicts
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Create all required directories BEFORE installing dependencies
RUN mkdir -p /workspace/ComfyUI/models/checkpoints \
    /workspace/ComfyUI/output \
    /workspace/ComfyUI/custom_nodes

# Install ComfyUI requirements
WORKDIR /workspace/ComfyUI
RUN pip install --no-cache-dir -r requirements.txt

# Install additional requirements
RUN pip install --no-cache-dir runpod boto3 requests huggingface_hub pillow

RUN git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git /workspace/ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation

# Install custom nodes with error handling and proper cleanup to save space
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git /workspace/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite || echo "Failed to clone ComfyUI-VideoHelperSuite, continuing anyway" && \
    git clone https://github.com/Acly/comfyui-tooling-nodes /workspace/ComfyUI/custom_nodes/comfyui-tooling-nodes || echo "Failed to clone tooling-nodes, continuing anyway"

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