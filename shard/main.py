import os
import requests
import threading
import time
import logging
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path

app = FastAPI(debug=True)

# Create the filesystem folder if it doesn't exist
filesystem_root = Path("filesystem")
filesystem_root.mkdir(exist_ok=True)

def poll_queue():
    while True:
        # Make a GET request to dequeue endpoint
        dequeue_url = f"http://{os.environ.get('QUEUE_HOST')}:{os.environ.get('QUEUE_PORT')}/dequeue"
        
        try:
            with httpx.Client() as client:
                response = client.get(dequeue_url)
                response.raise_for_status()
                
                data = response.json()
                print("Received items from queue:", data)
                
                # Process received items (assuming each item is a dict with id, target, body fields)
                for item in data:
                    # Process each item here
                    print(f"Processing item: {item['id']}, {item['target']}, {item['body']}")
                    
                    # Call own /chunk endpoint to save the chunk
                    chunk_url = f"http://localhost:{os.environ.get('PORT')}/chunk"
                    
                    payload = {
                        "chunk_hash": item["body"]["chunk_hash"],
                        "content": item["body"]["content"]
                    }
                    
                    try:
                        response = requests.post(chunk_url, json=payload)
                        response.raise_for_status()
                        print(f"Chunk successfully saved")
                    except requests.exceptions.RequestException as e:
                        print(f"Failed to save chunk: {str(e)}")
                    
        except httpx.RequestError as e:
            print(f"Error fetching items from queue: {str(e)}")
        
        time.sleep(5)  # Polling interval of 5 seconds


if not bool(os.environ.get("IS_MASTER")):
    thread = threading.Thread(target=poll_queue)
    thread.daemon = True
    thread.start()

class ChunkUpload(BaseModel):
    chunk_hash: str
    content: str
    
class ChunksDelete(BaseModel):
    chunk_hashes: list

@app.get("/")
def read_root():
    shard_id = os.environ.get("SHARD_ID", "1")
    return {"message": f"Hello from shard {shard_id}"}

@app.post("/chunk")
async def upload_file(item: ChunkUpload):
    chunk_hash = item.chunk_hash
    
    # Ensure the provided filepath is within the filesystem root
    full_path = filesystem_root / chunk_hash
    if not full_path.resolve().is_relative_to(filesystem_root.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filepath")

    # Create the directories if they don't exist
    full_path.parent.mkdir(parents=True, exist_ok=True)

    # Save the uploaded file
    with full_path.open("wb") as f:
        f.write(item.content.encode("utf-8"))
        
    if os.environ.get("IS_MASTER"):
        replica_host = os.environ.get("REPLICA_HOST")
        replica_port = os.environ.get("REPLICA_PORT")
        
        replica_url = f"http://{replica_host}:{replica_port}/chunk"
        
        payload = {
            "chunk_hash": item.chunk_hash,
            "content": item.content
        }
        
        try:
            response = requests.post(replica_url, json=payload)
            response.raise_for_status()
            print(f"Chunk successfully sent to replica service")
        except requests.exceptions.RequestException as e:
            print(f"Failed to send chunk to replica service: {str(e)}")

    return JSONResponse(content={"message": f"Chunk saved to {os.environ.get('SHARD_ID')}"}, status_code=201)

@app.get("/chunk/{chunk_hash}")
async def get_chunk(chunk_hash: str):
    full_path = filesystem_root / chunk_hash
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    with full_path.open("rb") as f:
        content = f.read().decode("utf-8")
    
    return JSONResponse(content={"chunk_hash": chunk_hash, "content": content}, status_code=200)

@app.delete("/chunk")
async def delete_chunks(item: ChunksDelete):
    chunk_hashes = item.chunk_hashes
    
    for chunk_hash in chunk_hashes:
        full_path = filesystem_root / chunk_hash
        if full_path.exists():
            os.remove(full_path)
            
    if os.environ.get("IS_MASTER"):
        replica_host = os.environ.get("REPLICA_HOST")
        replica_port = os.environ.get("REPLICA_PORT")
        
        replica_url = f"http://{replica_host}:{replica_port}/chunk"
        
        payload = {
            "chunk_hashes": chunk_hashes
        }
        
        try:
            response = requests.delete(replica_url, json=payload)
            response.raise_for_status()
            print(f"Chunks successfully deleted from replica service")
        except requests.exceptions.RequestException as e:
            print(f"Failed to delete chunks from replica service: {str(e)}")
    
    return JSONResponse(content={"message": "Chunks deleted successfully"}, status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT")))
