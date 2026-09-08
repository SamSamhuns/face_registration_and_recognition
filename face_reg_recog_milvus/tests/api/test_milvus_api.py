"""
Test milvus api
The milvus server must be running in the appropriate port
"""

import pytest
from app.api.milvus import get_registered_person_milvus
from tests.conftest import FACE_VECTOR_DIM, TEST_PERSON_FILE_ID


@pytest.mark.order(before="test_get_person_milvus")
def test_insert_person_milvus(test_milvus_connec):
    """Inserts a test person into Milvus."""
    emb_vec = [0.0] * FACE_VECTOR_DIM
    data = [[TEST_PERSON_FILE_ID], [emb_vec]]
    assert test_milvus_connec.insert(data).insert_count == 1


@pytest.mark.order(before="test_delete_person_milvus")
def test_get_person_milvus(test_milvus_connec):
    """Queries Milvus and retrieves the test person."""
    emb_vec = [0.0] * FACE_VECTOR_DIM
    res = get_registered_person_milvus(
        test_milvus_connec, TEST_PERSON_FILE_ID, output_fields=["person_id", "embedding"]
    )
    assert res["status"] == "success"
    results = res["person_data"]
    person_id = results[0]["person_id"]
    embedding = results[0]["embedding"]
    assert person_id == TEST_PERSON_FILE_ID, embedding == emb_vec


def test_delete_person_milvus(test_milvus_connec):
    """
    Deletes the test person from Milvus.

    Should call milvus_collec_conn.flush() and .compact(collec_name) after deletion.
    """
    expr = f"person_id in [{TEST_PERSON_FILE_ID}]"
    assert test_milvus_connec.delete(expr).delete_count == 1
