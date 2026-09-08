"""
Bulk insert faces and related person information into the milvus and sql database

CelebA dataset website: http://mmlab.ie.cuhk.edu.hk/projects/CelebA.html
Aligned faces dataset: https://drive.google.com/drive/folders/0B7EVK8r0v71pWEZsZE9oNnFzTm8?resourcekey=0-5BR16BdXnb8hVj6CNHKzLg
    images: img/img_align_celeba.zip
    annotations: Anno

Note only one face per celebrity is inserted into database (i.e. the first face alphabetically inside img_align_celeba)

Faces and related data must be inserted directly into milvus and mysql to reduce latency
First extract embeddings from faces and insert into milvus
Second insert related face data into mysql database

Run script as a module:
    # note the milvus & mysql services must be running already
    python -m scripts.bulk_insert_faces_into_milvus

requirements:
    # requirements from face_reg_recog_milvus/requirements.txt must also be installed
        pip install towhee==1.0.0rc1
"""

import glob
import os.path as osp
import random
import uuid
from datetime import date

import app.config as cfg
import pymysql
from app.api.milvus import get_milvus_collec_conn
from app.api.mysql import insert_person_data_into_sql
from app.models.model import PersonModel
from pymysql.cursors import DictCursor

IMG_EXTS = {".jpg", ".png", ".jpeg"}

# Connect to MySQL
mysql_conn = pymysql.connect(
    host=cfg.MYSQL_HOST,
    port=cfg.MYSQL_PORT,
    user=cfg.MYSQL_USER,
    password=cfg.MYSQL_PASSWORD,
    db=cfg.MYSQL_DATABASE,
    cursorclass=DictCursor,
)

# connect to milvus connec
milvus_collec_conn = get_milvus_collec_conn(
    collection_name=cfg.FACE_COLLECTION_NAME,
    milvus_host=cfg.MILVUS_HOST,
    milvus_port=cfg.MILVUS_PORT,
    vector_dim=cfg.FACE_VECTOR_DIM,
    metric_type=cfg.FACE_METRIC_TYPE,
    index_type=cfg.FACE_INDEX_TYPE,
    index_metric_params={},  # FLAT takes no tuning params
)


def insert_embeddings_into_milvus_towhee(img_dir: str):
    """
    reference nb: https://github.com/towhee-io/examples/blob/main/image/reverse_image_search/1_build_image_search_engine.ipynb
    """
    from towhee import ops, pipe, register

    insert_src_pat = osp.join(img_dir, "*.jpg")

    def load_image(path_pattern):
        """Yield image paths"""
        for item in glob.glob(path_pattern):
            yield from item

    @register
    def gen_int_id(x=None):
        """Get a unique int uuid"""
        return uuid.uuid1().int >> 64

    @register
    def get_facenet_emb(vec=None):
        """Get the embedding vector from a facenet model output"""
        return [list(map(float, vec[0]["embedding"]))]

    # Face embedding pipeline
    p_embed = (
        pipe.input("src")
        .flat_map("src", "img_path", load_image)
        .map("img_path", "img_id", gen_int_id())
        .map("img_path", "img", ops.image_decode())
        .map("img", "vec", ops.face_embedding.deepface(model_name="Facenet"))
        .map("vec", "emb", get_facenet_emb())
    )

    # WARNING, the processing time could be huge
    # p_out = p_embed.output("emb")(insert_src_pat).get()
    # print(len(p_out))

    # Insert pipeline
    p_insert = p_embed.map(
        ("emb", "img_id"),
        "mr",
        ops.ann_insert.milvus_client(
            host=cfg.MILVUS_HOST, port=cfg.MILVUS_PORT, collection_name=cfg.FACE_COLLECTION_NAME
        ),
    ).output("mr")

    # Insert data
    p_insert(insert_src_pat)

    # Check collection
    print("Number of data inserted:", milvus_collec_conn.num_entities)


def face_embedding_extractor_iter(img_dir: str):
    """
    function that yields face_vectors as an iterator from an img_dir
    """
    from app.services import faces

    imgs = sorted(glob.glob(osp.join(img_dir, "*")))
    imgs = [ip for ip in imgs if osp.splitext(ip)[-1] in IMG_EXTS]

    for file_path in imgs:
        try:
            embedding, _ = faces.embed_primary_face(
                faces.read_image(file_path),
                detector=cfg.FACE_DETECTOR,
                recognizer=cfg.FACE_RECOGNIZER,
                det_thresh=cfg.FACE_DET_THRESHOLD,
                min_area_fraction=cfg.FACE_MIN_AREA_FRACTION,
            )
        except faces.FaceError as excep:
            print(f"skipping {file_path}: {excep}")
            continue
        yield embedding.tolist()


def insert_embeddings_into_milvus_trt_sever(img_dir: str):
    """
    Inserts embeddings data in bulk into milvus
    """
    for face_vector in face_embedding_extractor_iter(img_dir):
        person_id = ""
        # insert face_vector into milvus milvus_collec_conn
        data = [[face_vector], [person_id]]
        milvus_collec_conn.insert(data)


def insert_data_into_mysql(img_dir: str):
    """
    Inserts data in bulk into mysql
    Each data should match the data model in PersonModel app/models/model.py
    """
    imgs = sorted(glob.glob(osp.join(img_dir, "*")))
    imgs = [ip for ip in imgs if osp.splitext(ip)[-1] in IMG_EXTS]
    imgs_iids = list(range(len(imgs)))
    data_list = [
        PersonModel(
            ID=iid,
            name=f"person_{iid}",
            birthdate=date(1971, random.randint(1, 12), random.randint(1, 28)),
            country=f"country_{random.randint(1, 1000)}",
        ).dict()
        for iid in imgs_iids
    ]

    ins = 0
    for data in data_list:
        rtn = insert_person_data_into_sql(mysql_conn, cfg.MYSQL_CUR_TABLE, data)
        if rtn["status"] == "success":
            ins += 1
    print(f"{ins} records successfully inserted into mysql table out of {len(data_list)} original data")


def main():
    """
    Main function, the img dir containing face images should be passed into the insert_data functions
    """
    # insert_embeddings_into_milvus_towhee(
    #     "../volumes/img_align_celeba_unique")
    insert_data_into_mysql("../volumes/img_align_celeba_unique")


if __name__ == "__main__":
    main()
