import hashlib
import json
import logging
import os
import random
import requests

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Response, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Annotated, List

from crud import authenticate_user, get_user_by_username, create_user as crud_create_user
from database import Base, get_db, engine
from schemas import User, UserCreate, Chunk, ChunkData, ChunkUpload


CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', 1024))
SCHEMA_MASTER_FILE = {}
SCHEMA_MASTER_FILE_PATH = '/app/schema_master.json'
HEADERS = { 'Content-Type': 'application/json' }
FILE_NOT_FOUND = "File not found"


# ===================================================================================


app = FastAPI()
Base.metadata.create_all(bind=engine)
security = HTTPBasic()


# ===================================================================================


@app.post("/users/", response_model=User)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud_create_user(db=db, user=user)


@app.get("/users/me", response_model=User)
def read_users_me(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def get_current_username(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user.username


@app.get("/users/username")
def read_current_user(username: Annotated[str, Depends(get_current_username)]):
    return {"username": username}

# ===================================================================================


def get_shards_uri() :
    """
    Request to get list of shards
    """
    shards = []
    shards_amount = int(os.environ.get('SHARDS_AMOUNT', 3))
    for i in range(shards_amount) :
        shard_host_i = os.environ.get('SHARD_%d_HOST' % (i+1))
        shard_port_i = os.environ.get('SHARD_%d_PORT' % (i+1))
        shards.append('http://%s:%s' % (shard_host_i, shard_port_i))
    return shards


def get_next_shard_uri(shards : List) :
    """
    Request to randomly get a shard from : @shards
    """
    r = random.randint(0, len(shards)-1)
    return shards[r], r


def to_hash_sha256(input_file_path: str) :
    """
    Request to make a hash of @input_file_path
    """
    sha256_hash = hashlib.sha256()
    sha256_hash.update(input_file_path.encode('utf-8'))
    hex_digest = sha256_hash.hexdigest()
    return hex_digest


def resolve_path(path: str) :
    """
    Request to get a valid path from
    """
    return str(Path(path).resolve())


def save_to_schema_master(data : ChunkData) :
    """
    Request to save @data to the schema master json
    """
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

    logging.info('JSON = %s', json.dumps(SCHEMA_MASTER_FILE, indent=2))

    with open(SCHEMA_MASTER_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write(json.dumps(SCHEMA_MASTER_FILE, indent=2))


def read_from_schema_master(user_id : str, file_path : str) :
    """
    Request to get all chunks of @file_path
    """
    if user_id not in SCHEMA_MASTER_FILE :
        return None

    if file_path not in SCHEMA_MASTER_FILE[user_id]['files'] :
        return None

    return SCHEMA_MASTER_FILE[user_id]['files'][file_path]['chunks']


def delete_from_schema_master(user_id : str, file_path : str) :
    """
    Request to delete all chunks from schema master of @file_path
    """
    if user_id not in SCHEMA_MASTER_FILE :
        return False

    if file_path not in SCHEMA_MASTER_FILE[user_id]['files'] :
        return False

    SCHEMA_MASTER_FILE[user_id]['files'].pop(file_path)

    logging.info('JSON = %s', json.dumps(SCHEMA_MASTER_FILE, indent=2))

    with open(SCHEMA_MASTER_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write(json.dumps(SCHEMA_MASTER_FILE, indent=2))

    return True


def read_size_from_schema_master(user_id, file_path : str) :
    """
    Request to get size of @file_path
    """
    if user_id not in SCHEMA_MASTER_FILE :
        return None

    if file_path not in SCHEMA_MASTER_FILE[user_id]['files'] :
        return None

    return SCHEMA_MASTER_FILE[user_id]['files'][file_path]['file_size']


# ===================================================================================


@app.get("/")
def read_root():
    return {"message": "Hello, World!"}


@app.post("/upload")
async def upload_file(
    file: Annotated[UploadFile, File()],
    file_path: Annotated[str, Form()],
    username: Annotated[str, Depends(get_current_username)]):

    logging.info("REST request to upload new file : %s", file_path)

    shards = get_shards_uri()
    chunk_id = 0

    data = ChunkData(
        user_id = username,
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

        next_shard, shard_id = get_next_shard_uri(shards)
        next_shard = next_shard + '/chunk'

        chunk_hash = to_hash_sha256('%s-%s-%d' % (username, file_path, chunk_id))
        chunk_upload = ChunkUpload(
            chunk_hash = chunk_hash,
            content = chunk_content)

        chunk_upload_dict = chunk_upload.dict()
        response = requests.post(next_shard, json=chunk_upload_dict, headers=HEADERS)

        if response.status_code == 201 :
            data.chunks.append(Chunk(
                shard_id = shard_id,
                chunk_hash = chunk_hash,
                chunk_size = chunk_size
            ))
        chunk_id = chunk_id + 1
    try:
        save_to_schema_master(data)
    except Exception as e:
        logging.error('An error occurred: %s', e)
        raise

    return {"filename": file.filename, 'data': data}


@app.get("/file")
async def get_file(
    file_path: Annotated[str, Form()],
    username: Annotated[str, Depends(get_current_username)]) :

    logging.info("REST request to get file : %s", file_path)

    shards = get_shards_uri()

    chunks = read_from_schema_master(username, resolve_path(file_path))

    file_array = []
    if not chunks:
        raise HTTPException(status_code=404, detail="File not found")

    for chunk in chunks :
        shard_uri = '%s/chunk/%s' % (shards[int(chunk['shard_id'])], chunk['chunk_hash'])
        response = requests.get(shard_uri, headers=HEADERS)

        if response.status_code == 200 :
            file_array.append(json.loads(response.text)['content'])
        else: raise HTTPException(status_code=400, detail="Error getting the file. Please try later.")
    return StreamingResponse(iter(file_array), media_type="text/plain", headers={"Content-Disposition": f"attachment; filename={os.path.basename(file_path)}"})


@app.get("/file_size")
async def get_file_size(
    file_path: Annotated[str, Form()],
    username: Annotated[str, Depends(get_current_username)]) :

    logging.info("REST request to get file size of %s", file_path)

    file_size = read_size_from_schema_master(username, resolve_path(file_path))

    if not file_size:
        raise HTTPException(status_code=404, detail=FILE_NOT_FOUND)

    return {
        'file_path': file_path,
        'file_size': file_size}


@app.delete("/file")
async def delete_file(
    file_path: Annotated[str, Form()],
    username: Annotated[str, Depends(get_current_username)]) :

    logging.info('REST request to delete file : %s', file_path)

    shards = get_shards_uri()

    chunks = read_from_schema_master(username, resolve_path(file_path))

    if not chunks:
        raise HTTPException(status_code=404, detail=FILE_NOT_FOUND)

    shard_hashes = [ [] for _ in range(len(shards)) ]

    for chunk in chunks :
        shard_hashes[chunk['shard_id']].append(chunk['chunk_hash'])

    for shard_id in range(len(shards)) :
        shard_uri = '%s/chunk' % shards[shard_id]
        requests.delete(shard_uri, headers=HEADERS, json=shard_hashes[shard_id])

    delete_from_schema_master(username, resolve_path(file_path))
    return Response(status_code=204)


if __name__ == "__main__":
    if not os.path.exists(SCHEMA_MASTER_FILE_PATH):
        with open(SCHEMA_MASTER_FILE_PATH, 'w', encoding='utf-8') as file:
            file.write('{}')

    with open(SCHEMA_MASTER_FILE_PATH, 'r', encoding='utf-8') as file:
        try:
            SCHEMA_MASTER_FILE = json.load(file)
        except json.JSONDecodeError:
            SCHEMA_MASTER_FILE = {}

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT")))

