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
    echo "Model file not found, initiating download process..."
    # Check if we have at least 6GB free
    FREE_SPACE=$(df -k /workspace | awk 'NR==2 {print $4}')
    echo "Available space: ${FREE_SPACE}KB"
    if [ "$FREE_SPACE" -lt 6000000 ]; then
        echo "Warning: Not enough disk space to download sv3d_u checkpoint (need at least 6GB)."
        echo "The service may not work properly. Consider increasing disk space allocation."
    else
        echo "Downloading sv3d_u checkpoint..."
        if [ -z "$HF_TOKEN" ]; then
            echo "Error: HF_TOKEN is required to download sv3d_u model."
            echo "HF_TOKEN environment variable is not set!"
            exit 1
        else
            echo "HF_TOKEN is set, proceeding with download..."
            wget --tries=3 --timeout=60 -O /workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors \
                --header="Authorization: Bearer ${HF_TOKEN}" \
                https://huggingface.co/stabilityai/sv3d/resolve/main/sv3d_u.safetensors || 
            echo "Warning: Failed to download sv3d_u checkpoint. The service may not work properly."
        fi
    fi
else
    echo "Model file already exists at /workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors"
    ls -l /workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors
fi

# Verify the model file exists and has content
if [ -f "/workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors" ]; then
    FILE_SIZE=$(stat -f%z "/workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors" 2>/dev/null || stat -c%s "/workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors")
    echo "Model file size: ${FILE_SIZE} bytes"
    if [ "$FILE_SIZE" -lt 1000000 ]; then
        echo "Warning: Model file exists but seems too small. May be corrupted or incomplete."
    fi
else
    echo "Error: Model file not found after download attempt!"
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
