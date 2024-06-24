import os
import random
import hashlib
import json
import requests
from typing import Annotated
from pathlib import Path
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dataclasses import dataclass
from typing import List, Dict

CHUNK_SIZE = 5
USER_ID = 1
SCHEMA_MASTER_FILE = {}
SCHEMA_MASTER_FILE_PATH = '/app/schema_master.json'

app = FastAPI()

def get_shards_uri() :
    shards = []
    shards_amount = int(os.environ.get('SHARDS_AMOUNT', 3))
    for i in range(shards_amount) :
        shard_host_i = os.environ.get('SHARD_%d_HOST' % (i+1))
        shard_port_i = os.environ.get('SHARD_%d_PORT' % (i+1))
        shards.append('http://%s:%s' % (shard_host_i, shard_port_i))
    # print(shards)
    return shards


def get_next_shard_uri(shards) :
    r = random.randint(0, len(shards)-1)
    print('rand', r)
    return shards[r], r


def to_hash_sha256(input_file_path: str) -> str:
    # Create a new SHA-256 hash object
    sha256_hash = hashlib.sha256()
    
    # Encode the input string and update the hash object
    sha256_hash.update(input_file_path.encode('utf-8'))
    
    # Get the hexadecimal representation of the hash
    hex_digest = sha256_hash.hexdigest()
    
    return hex_digest


def resolve_path(path) :
    return str(Path(path).resolve())


@dataclass
class Chunk:
    shard_id: int
    chunk_hash: str
    chunk_size: int

@dataclass
class ChunkData:
    user_id: str
    file_path: str
    file_size: int
    chunks: List[Chunk]


def save_to_schema_master(data : ChunkData) :

    print(SCHEMA_MASTER_FILE)
    
    if data.user_id not in SCHEMA_MASTER_FILE:
        SCHEMA_MASTER_FILE[data.user_id] = { 'files': {} }
    
    if data.file_path in SCHEMA_MASTER_FILE[data.user_id]['files'] :
        raise FileExistsError('File already exist!')
    
    SCHEMA_MASTER_FILE[data.user_id]['files'][data.file_path] = {
        'file_size': data.file_size,
        'chunks': [{
            'shard_id' : c.shard_id,
            'chunk_hash' : c.chunk_hash, 
            'chunk_size': c.chunk_size
            } for c in data.chunks]
    }

    print(json.dumps(SCHEMA_MASTER_FILE, indent=2))

    with open(SCHEMA_MASTER_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write(json.dumps(SCHEMA_MASTER_FILE, indent=2))


def read_from_schema_master(user_id, file_path : str) :
    print(json.dumps(SCHEMA_MASTER_FILE, indent=2))
    print(user_id)
    print(file_path)

    if user_id not in SCHEMA_MASTER_FILE :
        return None
    if file_path not in SCHEMA_MASTER_FILE[user_id]['files'] :
        return None
    return SCHEMA_MASTER_FILE[user_id]['files'][file_path]['chunks']


def delete_from_schema_master(user_id, file_path : str) :
    print(json.dumps(SCHEMA_MASTER_FILE, indent=2))
    print(user_id)
    print(file_path)

    if user_id not in SCHEMA_MASTER_FILE :
        return False
    if file_path not in SCHEMA_MASTER_FILE[user_id]['files'] :
        return False
    SCHEMA_MASTER_FILE[user_id]['files'].pop(file_path)
    return True


def read_size_from_schema_master(user_id, file_path : str) :
    print(json.dumps(SCHEMA_MASTER_FILE, indent=2))
    print(user_id)
    print(file_path)

    if user_id not in SCHEMA_MASTER_FILE :
        return None
    if file_path not in SCHEMA_MASTER_FILE[user_id]['files'] :
        return None
    return SCHEMA_MASTER_FILE[user_id]['files'][file_path]['file_size']


class ChunkUpload(BaseModel):
    chunk_hash: str
    content: str


@app.get("/")
def read_root():
    return {"message": "Hello, World!"}


@app.post("/upload")
async def upload_file(
    file: Annotated[UploadFile, File()],
    file_path: Annotated[str, Form()] ):

    shards = get_shards_uri()
    chunk_id = 0

    data = ChunkData(
        user_id = str(USER_ID),
        file_path = resolve_path(file_path),
        file_size = file.size,
        chunks = []
    )

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk :
            break
        chunk_content = chunk.decode('utf-8')
        chunk_size = len(chunk)
        print(chunk_content)
        next_shard, shard_id = get_next_shard_uri(shards)
        next_shard = next_shard + '/chunk'
        print(next_shard)
        chunk_hash = to_hash_sha256('%d-%s-%d' % (USER_ID, file_path, chunk_id))
        chunk_upload = ChunkUpload(
            chunk_hash = chunk_hash,
            content = chunk_content)
        print(chunk_upload.chunk_hash)
        print("POST")
        chunk_upload_dict = chunk_upload.dict()
        headers = {"Content-Type": "application/json"}
        response = requests.post(next_shard, json=chunk_upload_dict, headers=headers)
        print(response)
        print(response.text)
        if response.status_code == 201 :
            data.chunks.append(Chunk(
                shard_id = shard_id,
                chunk_hash = chunk_hash,
                chunk_size = chunk_size
            ))
        chunk_id = chunk_id + 1
    save_to_schema_master(data)

    return {"filename": file.filename, 'data': data}


@app.get("/file")
async def get_file(file_path: Annotated[str, Form()]) :
    shards = get_shards_uri()

    chunks = read_from_schema_master(str(USER_ID), resolve_path(file_path))
    print(chunks)
    file_array = []
    if not chunks:
        raise HTTPException(status_code=404, detail="File not found")

    for chunk in chunks :
        shard_uri = '%s/chunk/%s' % (shards[int(chunk['shard_id'])], chunk['chunk_hash'])
        headers = {"Content-Type": "application/json"}
        response = requests.get(shard_uri, headers=headers)
        print(response)
        print(response.text)
        file_array.append(json.loads(response.text)['content'])
    return StreamingResponse(iter(file_array), media_type="text/plain", headers={"Content-Disposition": f"attachment; filename={os.path.basename(file_path)}"})


@app.get("/file_size")
async def get_file_size(file_path: Annotated[str, Form()]) :
    file_size = read_size_from_schema_master(str(USER_ID), resolve_path(file_path))
    print(file_size)
    if not file_size:
        raise HTTPException(status_code=404, detail="File not found")

    return {
        'file_path': file_path,
        'file_size': file_size}


@app.delete("/file")
async def delete_file(file_path: Annotated[str, Form()]) :
    shards = get_shards_uri()

    chunks = read_from_schema_master(str(USER_ID), resolve_path(file_path))
    print(chunks)
    if not chunks:
        raise HTTPException(status_code=404, detail="File not found")

    shard_hashes = [ [] for _ in range(len(shards)) ]

    for chunk in chunks :
        shard_hashes[chunk['shard_id']].append(chunk['chunk_hash'])

    for shard_id in range(len(shards)) :
        shard_uri = '%s/chunk' % shards[shard_id]
        headers = {"Content-Type": "application/json"}
        response = requests.delete(shard_uri, headers=headers, json=shard_hashes[shard_id])
        print(response)
    delete_from_schema_master(str(USER_ID), resolve_path(file_path))
    return Response(status_code=204)


if __name__ == "__main__":
    # Check if the file exists
    if not os.path.exists(SCHEMA_MASTER_FILE_PATH):
        # Create an empty file if it doesn't exist
        with open(SCHEMA_MASTER_FILE_PATH, 'w', encoding='utf-8') as file:
            file.write('{}')

    # Load the JSON data from the file
    with open(SCHEMA_MASTER_FILE_PATH, 'r', encoding='utf-8') as file:
        try:
            SCHEMA_MASTER_FILE = json.load(file)
        except json.JSONDecodeError:
            # Handle JSON decoding error (e.g., file is empty or corrupted)
            SCHEMA_MASTER_FILE = {}
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT")))

