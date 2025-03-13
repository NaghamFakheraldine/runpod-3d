import os
import json
import time
import base64
import runpod
import subprocess
import threading
import requests
import sys
import logging
from io import BytesIO
from PIL import Image

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("comfyui-handler")

# Configuration
COMFYUI_PORT = 8188
MAX_STARTUP_RETRIES = 120
STARTUP_RETRY_INTERVAL = 5
MAX_PROCESSING_RETRIES = 600
PROCESSING_RETRY_INTERVAL = 2
REQUEST_TIMEOUT = 60

# Check required dependencies
def check_dependencies():
    try:
        import numpy
        logger.info(f"NumPy version: {numpy.__version__}")
        
        import torch
        logger.info(f"PyTorch version: {torch.__version__}")
        logger.info(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"CUDA version: {torch.version.cuda}")
        
        import torchaudio
        logger.info(f"TorchAudio version: {torchaudio.__version__}")
        
        # Check FFmpeg
        try:
            import imageio_ffmpeg
            logger.info(f"imageio-ffmpeg version: {imageio_ffmpeg.__version__}")
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            logger.info(f"FFmpeg path: {ffmpeg_path}")
        except ImportError:
            logger.error("imageio-ffmpeg is not installed!")
            raise
        except Exception as e:
            logger.error(f"Error checking FFmpeg: {str(e)}")
            raise
            
    except ImportError as e:
        logger.error(f"Missing required dependency: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error checking dependencies: {str(e)}")
        raise

# Start ComfyUI as a background process
def start_comfyui():
    logger.info("Starting ComfyUI server...")
    try:
        # Check dependencies first
        check_dependencies()
        
        process = subprocess.Popen(
            ["python", "main.py", "--listen", "0.0.0.0", "--port", str(COMFYUI_PORT), "--cuda-device", "0"],
            cwd="/workspace/ComfyUI",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Log output in separate threads
        def log_output(pipe, level):
            for line in pipe:
                if level == "INFO":
                    logger.info(f"ComfyUI: {line.strip()}")
                else:
                    logger.error(f"ComfyUI: {line.strip()}")
                    
        threading.Thread(target=log_output, args=(process.stdout, "INFO"), daemon=True).start()
        threading.Thread(target=log_output, args=(process.stderr, "ERROR"), daemon=True).start()
        
        return process
    except Exception as e:
        logger.error(f"Error starting ComfyUI: {str(e)}")
        raise

# Wait for ComfyUI to be ready
def wait_for_comfyui():
    logger.info(f"Waiting for ComfyUI server to be ready (max {MAX_STARTUP_RETRIES * STARTUP_RETRY_INTERVAL}s)...")
    
    for retry in range(MAX_STARTUP_RETRIES):
        try:
            response = requests.get(f"http://127.0.0.1:{COMFYUI_PORT}/system_stats", timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                logger.info("ComfyUI server is ready!")
                return True
            else:
                logger.warning(f"ComfyUI returned status code {response.status_code}, retrying...")
        except requests.exceptions.ConnectionError:
            logger.info(f"Waiting for ComfyUI to start (attempt {retry+1}/{MAX_STARTUP_RETRIES})...")
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout while checking ComfyUI status (attempt {retry+1}/{MAX_STARTUP_RETRIES})")
        except Exception as e:
            logger.warning(f"Error checking ComfyUI status: {str(e)}")
        
        time.sleep(STARTUP_RETRY_INTERVAL)
    
    raise Exception(f"ComfyUI server failed to start after {MAX_STARTUP_RETRIES * STARTUP_RETRY_INTERVAL} seconds")

# Process the workflow
def process_workflow(workflow_data):
    logger.info("Processing workflow...")
    
    # Queue the workflow
    api_endpoint = f"http://127.0.0.1:{COMFYUI_PORT}/prompt"
    
    try:
        logger.info("Sending workflow to ComfyUI...")
        response = requests.post(
            api_endpoint,
            json={
                "prompt": workflow_data,
                "extra_data": {
                    "extra_pnginfo": {
                        "workflow": workflow_data
                    }
                }
            },
            timeout=30
        )
        
        if response.status_code != 200:
            error_msg = f"Failed to queue workflow: {response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        execution_id = response.json()["prompt_id"]
        logger.info(f"Workflow queued with ID: {execution_id}")
    except requests.exceptions.RequestException as e:
        error_msg = f"Error sending workflow to ComfyUI: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    # Poll for results
    logger.info(f"Waiting for results (max {MAX_PROCESSING_RETRIES * PROCESSING_RETRY_INTERVAL}s)...")
    
    for retry in range(MAX_PROCESSING_RETRIES):
        try:
            response = requests.get(f"http://127.0.0.1:{COMFYUI_PORT}/history", timeout=10)
            history = response.json()
            
            if execution_id in history:
                execution_data = history[execution_id]
                
                # Check if processing is complete
                if "outputs" in execution_data and execution_data.get("status", {}).get("status") == "success":
                    logger.info("Workflow processing completed successfully")
                    
                    # Find the output video (node 24)
                    for node_id, node_output in execution_data["outputs"].items():
                        if node_id == "24":
                            if "videos" in node_output:
                                video_data = node_output["videos"][0]
                                video_path = f"/workspace/ComfyUI/output/{video_data['filename']}"
                                logger.info(f"Found output video: {video_path}")
                                
                                # Return base64 encoded video
                                try:
                                    with open(video_path, "rb") as video_file:
                                        video_base64 = base64.b64encode(video_file.read()).decode("utf-8")
                                    
                                    return {
                                        "status": "success",
                                        "video": video_base64,
                                        "execution_id": execution_id
                                    }
                                except Exception as e:
                                    error_msg = f"Error reading output video: {str(e)}"
                                    logger.error(error_msg)
                                    return {"status": "error", "message": error_msg}
                    
                    # If we get here, the workflow completed but we couldn't find the video
                    error_msg = "No output video found in results"
                    logger.error(error_msg)
                    return {"status": "error", "message": error_msg}
                
                # Check if there was an error
                if execution_data.get("status", {}).get("status") == "error":
                    error_msg = execution_data.get("status", {}).get("message", "Unknown error in workflow processing")
                    logger.error(f"Workflow processing failed: {error_msg}")
                    return {"status": "error", "message": error_msg}
                
                # Still processing
                status = execution_data.get("status", {}).get("status", "unknown")
                logger.info(f"Still processing (status: {status}), retrying... ({retry+1}/{MAX_PROCESSING_RETRIES})")
            else:
                logger.info(f"Execution ID not found in history yet, retrying... ({retry+1}/{MAX_PROCESSING_RETRIES})")
        
        except Exception as e:
            logger.warning(f"Error checking workflow status: {str(e)}")
        
        time.sleep(PROCESSING_RETRY_INTERVAL)
    
    error_msg = f"Timeout waiting for results after {MAX_PROCESSING_RETRIES * PROCESSING_RETRY_INTERVAL} seconds"
    logger.error(error_msg)
    return {"status": "error", "message": error_msg}

# Handler function for RunPod
def handler(event):
    try:
        logger.info(f"Received event: {json.dumps(event.get('input', {}))[:1000]}...")
        
        # Get the workflow and image from the input
        workflow_data = event.get("input", {}).get("workflow")
        input_image = event.get("input", {}).get("image", "")
        
        # If workflow is not provided, use the default one
        if not workflow_data:
            try:
                with open("/workspace/workflow.json", "r") as f:
                    workflow_data = json.load(f)
                logger.info("Using default workflow from workflow.json")
            except Exception as e:
                error_msg = f"Error loading default workflow: {str(e)}"
                logger.error(error_msg)
                return {"status": "error", "message": error_msg}
        
        # Set the input image in the workflow
        if input_image:
            if "58" in workflow_data:
                logger.info("Setting input image in node 58")
                workflow_data["58"]["inputs"]["image"] = input_image
            else:
                error_msg = "Node 58 (ETN_LoadImageBase64) not found in workflow"
                logger.error(error_msg)
                return {"status": "error", "message": error_msg}
        else:
            error_msg = "No input image provided"
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}
        
        # Process the workflow
        result = process_workflow(workflow_data)
        logger.info(f"Processing completed with status: {result.get('status')}")
        return result
    
    except Exception as e:
        error_msg = f"Error in handler: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "message": error_msg}

# Main function
if __name__ == "__main__":
    try:
        # Start ComfyUI
        comfyui_process = start_comfyui()
        
        # Wait for ComfyUI to be ready
        wait_for_comfyui()
        
        # Start the RunPod serverless handler
        logger.info("Starting RunPod handler...")
        runpod.serverless.start({"handler": handler})
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)