import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path

app = FastAPI()

# Create the filesystem folder if it doesn't exist
filesystem_root = Path("filesystem")
filesystem_root.mkdir(exist_ok=True)

class ChunkUpload(BaseModel):
    chunk_hash: str
    content: str

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

    return JSONResponse(content={"message": f"Chunk saved to {os.environ.get('SHARD_ID', '1')}"}, status_code=201)

@app.get("/chunk/{chunk_hash}")
async def get_chunk(chunk_hash: str):
    full_path = filesystem_root / chunk_hash
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    with full_path.open("rb") as f:
        content = f.read().decode("utf-8")
    
    return JSONResponse(content={"chunk_hash": chunk_hash, "content": content}, status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
