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

# Download sv3d_u checkpoint with disk space check and verification
MODEL_PATH="/workspace/ComfyUI/models/checkpoints/sv3d_u.safetensors"
if [ ! -f "$MODEL_PATH" ] || [ ! -s "$MODEL_PATH" ]; then
    echo "Model file not found or empty, initiating download process..."
    # Check if we have at least 6GB free
    FREE_SPACE=$(df -k /workspace | awk 'NR==2 {print $4}')
    echo "Available space: ${FREE_SPACE}KB"
    if [ "$FREE_SPACE" -lt 6000000 ]; then
        echo "Error: Not enough disk space to download sv3d_u checkpoint (need at least 6GB)."
        exit 1
    else
        echo "Downloading sv3d_u checkpoint..."
        if [ -z "$HF_TOKEN" ]; then
            echo "Error: HF_TOKEN is required to download sv3d_u model."
            echo "HF_TOKEN environment variable is not set!"
            exit 1
        else
            echo "HF_TOKEN is set, proceeding with download..."
            rm -f "$MODEL_PATH"  # Remove any existing incomplete file
            wget --tries=3 --timeout=60 -O "$MODEL_PATH" \
                --header="Authorization: Bearer ${HF_TOKEN}" \
                https://huggingface.co/stabilityai/sv3d/resolve/main/sv3d_u.safetensors
            
            # Verify download
            if [ ! -f "$MODEL_PATH" ] || [ ! -s "$MODEL_PATH" ]; then
                echo "Error: Failed to download model or file is empty"
                exit 1
            fi
            
            # Check file size (should be around 5GB)
            FILE_SIZE=$(stat -f%z "$MODEL_PATH" 2>/dev/null || stat -c%s "$MODEL_PATH")
            if [ "$FILE_SIZE" -lt 5000000000 ]; then  # 5GB in bytes
                echo "Error: Downloaded model file is too small, might be corrupted"
                rm -f "$MODEL_PATH"
                exit 1
            fi
            echo "Model downloaded successfully. Size: $(numfmt --to=iec-i --suffix=B $FILE_SIZE)"
        fi
    fi
else
    echo "Model file exists at $MODEL_PATH"
    FILE_SIZE=$(stat -f%z "$MODEL_PATH" 2>/dev/null || stat -c%s "$MODEL_PATH")
    echo "Model file size: $(numfmt --to=iec-i --suffix=B $FILE_SIZE)"
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