"""
pymysql api functions
"""

import logging

import pymysql

logger = logging.getLogger("mysql_api")


def insert_person_data_into_sql(mysql_conn, mysql_tb, person_data: dict, commit: bool = True) -> dict:
    """
    Insert person_data into mysql table with param binding
    Note: the transaction must be committed after if commit is False
    """
    # query fmt: `INSERT INTO mysql_tb (id, col1_name, col2_name) VALUES (%s, %s, %s)`
    query = (
        f"INSERT INTO {mysql_tb}"
        + f" {tuple(person_data.keys())}"
        + f" VALUES ({', '.join(['%s'] * len(person_data))})"
    ).replace("'", "")
    values = tuple(person_data.values())
    try:
        with mysql_conn.cursor() as cursor:
            cursor.execute(query, values)
            if commit:
                mysql_conn.commit()
                logger.info("record inserted into mysql db.✅️")
                return {"status": "success", "message": "record inserted into mysql db"}
            logger.info("record insertion waiting to be commit to mysql db.🕓")
            return {"status": "success", "message": "record insertion waiting to be commit to mysql db."}
    except pymysql.Error as exception:
        logger.error("%s: mysql record insert failed ❌", exception)
        return {"status": "failed", "message": "mysql record insertion error"}


def select_person_data_from_sql_with_id(mysql_conn, mysql_tb, person_id: int) -> dict:
    """
    Query mysql db to get full person data using the uniq person_id
    """
    query = f"SELECT * FROM {mysql_tb} WHERE id = %s"
    values = person_id
    try:
        with mysql_conn.cursor() as cursor:
            cursor.execute(query, values)
            person_data = cursor.fetchone()
            if person_data is None:
                logger.warning("mysql record with id: %s does not exist ❌.", person_id)
                return {"status": "failed", "message": f"mysql record with id: {person_id} does not exist"}
            logger.info("Person with id: %s retrieved from mysql db.✅️", person_id)
            return {
                "status": "success",
                "message": f"record matching id: {person_id} retrieved from mysql db",
                "person_data": person_data,
            }
    except pymysql.Error as exception:
        logger.error("%s: mysql record retrieval failed ❌", exception)
        return {"status": "failed", "message": "mysql record retrieval error"}


def select_all_person_data_from_sql(mysql_conn, mysql_tb) -> dict:
    """
    Query mysql db to get all person data
    """
    query = f"SELECT * FROM {mysql_tb}"
    try:
        with mysql_conn.cursor() as cursor:
            cursor.execute(query)
            person_data = cursor.fetchall()
            if person_data is None:
                logger.warning("No mysql person records were found ❌.")
                return {"status": "failed", "message": "No mysql person records were found."}
            logger.info("All persons records retrieved from mysql db.✅️")
            return {
                "status": "success",
                "message": "All person records retrieved from mysql db",
                "person_data": person_data,
            }
    except pymysql.Error as exception:
        logger.error("%s: mysql record retrieval failed ❌", exception)
        return {"status": "failed", "message": "mysql record retrieval error"}


def delete_person_data_from_sql_with_id(mysql_conn, mysql_tb, person_id: int, commit: bool = True) -> dict:
    """
    Delete record from mysql db using the uniq person_id
    """
    select_query = f"SELECT * FROM {mysql_tb} WHERE id = %s"
    del_query = f"DELETE FROM {mysql_tb} WHERE id = %s"
    try:
        with mysql_conn.cursor() as cursor:
            # check if record exists in db or not
            cursor.execute(select_query, (person_id))
            if not cursor.fetchone():
                logger.error("Person with id: %s does not exist in mysql db.❌", person_id)
                return {"status": "failed", "message": f"mysql record with id: {person_id} does not exist in db"}

            cursor.execute(del_query, (person_id))
            if commit:
                mysql_conn.commit()
                logger.info("Person with id: %s deleted from mysql db.✅️", person_id)
                return {"status": "success", "message": "record deleted from mysql db"}
            logger.info("record deletion waiting to be committed to mysql db.🕓")
            return {"status": "success", "message": "record deletion waiting to be committed to mysql db."}
    except pymysql.Error as exception:
        logger.error("%s: mysql record deletion failed ❌", exception)
        return {"status": "failed", "message": "mysql record deletion error"}
