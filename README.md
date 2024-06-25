# Pera Team Filesystem

## Architecture

The entry point of the filesystem is the `server` service. It is exposed by default in the <http://0.0.0.0:4000>. The system consists of a naming server, shards, replicas and a mysql database. The naming server receives all direct requests from the user, including their files and requests for files.

When receiving a file, the server splits it into 1KB (modifiable) chunks and randomly distributes them among the shards. The server user a file called `schema_master.json` as a key-value storage of the location of every users' files. For each file it uses its path as a key, and stores on which replicas each chunk is located.

A chunk is identified by a hash, so when the naming server asks a shard for a chunk, it send the desired hash, and the shard is responsible for returning the correct contents. Finally the naming server joins the fetched contents and sends it to the client.

It is also possible to delete an uploaded file.

Replicas updating is sync. When a shard receives a chunk or a delete request, it takes care of sending that information to its replica (1 per shard as an example). Also, when the naming server is fetching chunks, it will first try to fetch from the master shards, and if some of those fail, it will try to fetch from their corresponding replicas.

## Authentication

The filesystem supports basic authentication so each user can have their own filesystem. Each request must come with basic authentication headers, providing the username and password (you can easily do this with Postman). Also, the system is secured so no user can access other user's files, and to allow that different users may have files with the same name and route without arising conflicts. The authentication data is stored in a mysql database.

## Running

To run the filesystem, you must have Docker installed. Then, you can run the following command:

```bash
docker compose build && docker compose up -d
```

There is a small chance that the first time you run the containers `server` service will start before the `mysql-auth` service, so if you see any error, just run the command again.

## Endpoints

### POST /user

This endpoint allows the user to create a new user in the filesystem. The request must contain the username and password of the new user.

#### Request

```json
{
  "username": "username",
  "password": "password"
}
```

### POST /upload

This endpoint allows the user to upload a file to the filesystem. The request must contain the file in the body and the path where the file will be stored in the filesystem (for simplicity, submit as `form-data` in Postman).

#### Request

```json
{
  "file_path": "/path/to/file",
  "file": <file>
}
```

### GET /file

This endpoint allows the user to download a file from the filesystem. The request must contain the path of the file to be downloaded.

#### Request

```json
{
  "file_path": "/path/to/file"
}
```

### GET /file_size

This endpoint allows the user to get the size of a file in the filesystem. The request must contain the path of the file to get the size.

#### Request

```json
{
  "file_path": "/path/to/file"
}
```

### DELETE /file

This endpoint allows the user to delete a file from the filesystem. The request must contain the path of the file to be deleted.

#### Request

```json
{
  "file_path": "/path/to/file"
}
```