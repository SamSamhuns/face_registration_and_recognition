-- database and table names are acquired from env variables
CREATE DATABASE IF NOT EXISTS `default`;
USE `default`;

-- create PERSON table
CREATE TABLE IF NOT EXISTS person (
    ID INT NOT NULL,

    name VARCHAR(255) NOT NULL,
    birthdate DATE NOT NULL,
    country VARCHAR(255) NOT NULL,
    city VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    org VARCHAR(255) NOT NULL,

    PRIMARY KEY (ID)
);