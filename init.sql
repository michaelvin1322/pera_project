CREATE USER 'pera_user'@'localhost' IDENTIFIED BY 'password';

CREATE DATABASE auth_db;

GRANT ALL PRIVILEGES ON auth_db.* TO 'pera_user'@'localhost';

FLUSH PRIVILEGES;

SHOW GRANTS FOR 'pera_user'@'localhost';

EXIT;

