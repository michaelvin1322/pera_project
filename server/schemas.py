from dataclasses import dataclass
from pydantic import BaseModel
from typing import List


class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int

    class Config:
        orm_mode = True


class ChunkUpload(BaseModel):
    chunk_hash: str
    content: str


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
