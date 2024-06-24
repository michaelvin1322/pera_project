import os
import random
import hashlib
import requests
from typing import Annotated
from pathlib import Path
from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

CHUNK_SIZE = 5

app = FastAPI()

def get_shards_uri() :
    shards = []
    shards_amount = os.environ.get('SHARDS_AMOUNT')
    for i in range(shards_amount) :
        shards.push('SHARD_%_HOST:SHARD_%_PORT' % (i, i))
    return shards


def get_next_shard_uri(shards) :
    r = random.randint(1, len(shards))
    return shards[r]


def to_hash_sha256(input_file_path: str) -> str:
    # Create a new SHA-256 hash object
    sha256_hash = hashlib.sha256()
    
    # Encode the input string and update the hash object
    sha256_hash.update(input_file_path.encode('utf-8'))
    
    # Get the hexadecimal representation of the hash
    hex_digest = sha256_hash.hexdigest()
    
    return hex_digest


def resolve_path(path) :
    return Path(path).resolve()


@app.get("/")
def read_root():
    return {"message": "Hello, World!"}


class ChunkUpload(BaseModel):
    chunk_hash: str
    content: str


@app.post("/upload")
async def upload_file(
    file: Annotated[UploadFile, File()],
    file_path: Annotated[str, Form()] ):

    shards = get_shards_uri()

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk :
            break
        chunk_content = chunk.decode('utf-8')
        next_shard = get_next_shard_uri(shards) + '/chunk'
        chunk_upload = ChunkUpload()
        chunk_upload.chunk_hash = to_hash_sha256(file_path)
        chunk_upload.content = chunk_content
        response = requests.post(next_shard, data=chunk_upload)
        print(response)
        print(response.text)

    return {"filename": file.filename, "file_size": file.size, "file_path": resolve_path(file_path), "ct": file.content_type}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=os.environ.get("PORT"))

