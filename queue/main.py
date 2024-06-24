import os
import json
import mysql.connector
from mysql.connector import errorcode
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Define the database configuration
config = {
    'user': os.environ.get('MYSQL_USER'),
    'password': os.environ.get('MYSQL_PASSWORD'),
    'host': os.environ.get('MYSQL_HOST'),
    'database': os.environ.get('MYSQL_DATABASE')
}

# Establish the database connection
try:
    cnx = mysql.connector.connect(**config)
    cursor = cnx.cursor()

    # SQL statement to create the jobs table
    create_table_query = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        target VARCHAR(255) NOT NULL,
        body JSON NOT NULL
    );
    """

    # Execute the SQL statement
    cursor.execute(create_table_query)
    print("Table `jobs` created successfully.")

except mysql.connector.Error as err:
    if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
        print("Something is wrong with your user name or password")
    elif err.errno == errorcode.ER_BAD_DB_ERROR:
        print("Database does not exist")
    else:
        print(err)
else:
    cursor.close()
    cnx.close()

app = FastAPI()

class ChunkUpload(BaseModel):
    chunk_hash: str
    content: str

@app.post("/enqueue")
async def enqueue_job(target: str, body: ChunkUpload):
    jsonBody = json.dumps(body.model_dump())
    # Save the job to the database
    try:
        cnx = mysql.connector.connect(**config)
        cursor = cnx.cursor()

        # SQL statement to insert a new job
        insert_job_query = """
        INSERT INTO jobs (target, body) VALUES (%s, %s);
        """

        # Execute the SQL statement
        cursor.execute(insert_job_query, (target, jsonBody))
        cnx.commit()
        return JSONResponse(content={"message": "Job enqueued successfully"}, status_code=201)

    except mysql.connector.Error as err:
        print(err)
        return JSONResponse(content={"message": "An error occurred"}, status_code=500)
    finally:
        cursor.close()
        cnx.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT")))