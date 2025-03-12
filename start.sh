#!/bin/bash
set -e

echo "Starting RunPod ComfyUI service..."

# Function to handle errors
handle_error() {
    echo "Error occurred in start.sh at line $1"
    exit 1
}

# Set trap for error handling
trap 'handle_error $LINENO' ERR

# Create directories if they don't exist (double-check)
mkdir -p /workspace/ComfyUI/models/checkpoints
mkdir -p /workspace/ComfyUI/output

# Check disk space before downloads
echo "Checking available disk space..."
df -h /workspace

# Download sv3d_u checkpoint with disk space check
if [ ! -f "/workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors" ]; then
    # Check if we have at least 6GB free
    FREE_SPACE=$(df -k /workspace | awk 'NR==2 {print $4}')
    if [ "$FREE_SPACE" -lt 6000000 ]; then
        echo "Warning: Not enough disk space to download sv3d_u checkpoint (need at least 6GB)."
        echo "The service may not work properly. Consider increasing disk space allocation."
    else
        echo "Downloading sv3d_u checkpoint..."
        if [ -z "$HF_TOKEN" ]; then
            echo "Error: HF_TOKEN is required to download sv3d_u model."
            exit 1
        else
            wget --tries=3 --timeout=60 -O /workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors \
                --header="Authorization: Bearer ${HF_TOKEN}" \
                https://huggingface.co/stabilityai/sv3d/resolve/main/sv3d_u.safetensors || 
            echo "Warning: Failed to download sv3d_u checkpoint. The service may not work properly."
        fi
    fi
fi

# Manage workflow.json
echo "Setting up workflow file..."
if [ -f "/runpod-volume/workflow.json" ]; then
    echo "Found workflow.json in volume mount, copying to workspace."
    cp /runpod-volume/workflow.json /workspace/workflow.json
elif [ ! -s "/workspace/workflow.json" ]; then
    echo "Creating workflow.json from workflow.json..."
    cp /workspace/workflow.json /workspace/workflow.json
fi

# Display disk usage after setup
echo "Disk usage after setup:"
df -h /workspace

# Start the RunPod handler
echo "Starting RunPod handler..."
python3 -u /workspace/handler.py

# Verify the downloaded file
ls -l /workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors