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
MAX_STARTUP_RETRIES = 60
STARTUP_RETRY_INTERVAL = 5
MAX_PROCESSING_RETRIES = 300
PROCESSING_RETRY_INTERVAL = 2

# Start ComfyUI as a background process
def start_comfyui():
    logger.info("Starting ComfyUI server...")
    try:
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
            response = requests.get(f"http://127.0.0.1:{COMFYUI_PORT}/system_stats")
            if response.status_code == 200:
                logger.info("ComfyUI server is ready!")
                return True
            else:
                logger.warning(f"ComfyUI returned status code {response.status_code}, retrying...")
        except requests.exceptions.ConnectionError:
            logger.info(f"Waiting for ComfyUI to start (attempt {retry+1}/{MAX_STARTUP_RETRIES})...")
        except Exception as e:
            logger.warning(f"Error checking ComfyUI status: {str(e)}")
        
        time.sleep(STARTUP_RETRY_INTERVAL)
    
    raise Exception(f"ComfyUI server failed to start after {MAX_STARTUP_RETRIES * STARTUP_RETRY_INTERVAL} seconds")

# Process the workflow
def process_workflow(workflow_data, prompt=""):
    logger.info("Processing workflow...")
    
    # Update the prompt in the workflow if provided
    if prompt:
        if "39" in workflow_data:
            bged_prompt = f"bged {prompt}"  # Prepend 'bged' to the prompt
            logger.info(f"Setting prompt in node 39: {bged_prompt}")
            workflow_data["39"]["inputs"]["text"] = bged_prompt
        else:
            logger.warning("Node 39 not found in workflow, prompt will not be applied")
    
    # Queue the prompt
    prompt_api = f"http://127.0.0.1:{COMFYUI_PORT}/prompt"
    
    try:
        logger.info("Sending prompt to ComfyUI...")
        response = requests.post(
            prompt_api,
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
            error_msg = f"Failed to queue prompt: {response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        prompt_id = response.json()["prompt_id"]
        logger.info(f"Prompt queued with ID: {prompt_id}")
    except requests.exceptions.RequestException as e:
        error_msg = f"Error sending prompt to ComfyUI: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    # Poll for results
    logger.info(f"Waiting for results (max {MAX_PROCESSING_RETRIES * PROCESSING_RETRY_INTERVAL}s)...")
    
    for retry in range(MAX_PROCESSING_RETRIES):
        try:
            response = requests.get(f"http://127.0.0.1:{COMFYUI_PORT}/history", timeout=10)
            history = response.json()
            
            if prompt_id in history:
                prompt_data = history[prompt_id]
                
                # Check if processing is complete
                if "outputs" in prompt_data and prompt_data.get("status", {}).get("status") == "success":
                    logger.info("Workflow processing completed successfully")
                    
                    # Find the output image (node 113)
                    for node_id, node_output in prompt_data["outputs"].items():
                        if node_id == "113" and node_output.get("images"):
                            image_data = node_output["images"][0]
                            image_path = f"/workspace/ComfyUI/output/{image_data['filename']}"
                            logger.info(f"Found output image: {image_path}")
                            
                            # Return base64 encoded image
                            try:
                                with open(image_path, "rb") as img_file:
                                    img_base64 = base64.b64encode(img_file.read()).decode("utf-8")
                                
                                return {
                                    "status": "success",
                                    "image": img_base64,
                                    "prompt_id": prompt_id
                                }
                            except Exception as e:
                                error_msg = f"Error reading output image: {str(e)}"
                                logger.error(error_msg)
                                return {"status": "error", "message": error_msg}
                    
                    # If we get here, the prompt completed but we couldn't find the image
                    error_msg = "No output image found in results"
                    logger.error(error_msg)
                    return {"status": "error", "message": error_msg}
                
                # Check if there was an error
                if prompt_data.get("status", {}).get("status") == "error":
                    error_msg = prompt_data.get("status", {}).get("message", "Unknown error in workflow processing")
                    logger.error(f"Workflow processing failed: {error_msg}")
                    return {"status": "error", "message": error_msg}
                
                # Still processing
                status = prompt_data.get("status", {}).get("status", "unknown")
                logger.info(f"Still processing (status: {status}), retrying... ({retry+1}/{MAX_PROCESSING_RETRIES})")
            else:
                logger.info(f"Prompt ID not found in history yet, retrying... ({retry+1}/{MAX_PROCESSING_RETRIES})")
        
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
        
        # Get the workflow from the input
        workflow_data = event.get("input", {}).get("workflow")
        prompt = event.get("input", {}).get("prompt", "")
        
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
        
        # Process the workflow
        result = process_workflow(workflow_data, prompt)
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