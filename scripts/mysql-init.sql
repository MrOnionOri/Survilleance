CREATE DATABASE IF NOT EXISTS streamwatch
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'streamwatch'@'localhost'
  IDENTIFIED BY 'streamwatch';

GRANT ALL PRIVILEGES ON streamwatch.* TO 'streamwatch'@'localhost';
FLUSH PRIVILEGES;
