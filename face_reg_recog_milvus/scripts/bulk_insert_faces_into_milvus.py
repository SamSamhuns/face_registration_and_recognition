"""
Bulk load a directory of face images into MySQL and Milvus.

Each image becomes one person. The SQL row and the face vector always get the same
id, so a later recognition can join them.

    python -m scripts.bulk_insert_faces_into_milvus <image_dir> [--start-id 1]

Run it from the directory that contains `app/`, with the same environment the API
uses. It writes through the same service layer as the API, so the detector, the
recogniser and the target collection all follow the FACE_* settings.

Person names and dates here are placeholders. Replace generate_person() if the
directory carries real identity metadata, for example the CelebA identity file.
"""

import argparse
import asyncio
import glob
import os.path as osp
from datetime import date

from app.config import FACE_COLLECTION_NAME, MYSQL_CUR_TABLE
from app.db import persons, vectors
from app.deps import close_clients, create_clients
from app.errors import AppError
from app.schemas import PersonCreate
from app.services import enroll, faces

IMG_EXTS = {".jpg", ".jpeg", ".png"}


def find_images(img_dir: str) -> list[str]:
    """Return the sorted image paths in img_dir."""
    paths = sorted(glob.glob(osp.join(img_dir, "*")))
    return [p for p in paths if osp.splitext(p)[-1].lower() in IMG_EXTS]


def generate_person(person_id: int, image_path: str) -> PersonCreate:
    """Build a placeholder record for one image."""
    return PersonCreate(
        id=person_id,
        name=osp.splitext(osp.basename(image_path))[0],
        birthdate=date(1990, 1, 1),
        country="unknown",
    )


async def load(img_dir: str, start_id: int) -> None:
    images = find_images(img_dir)
    if not images:
        print(f"no images found in {img_dir}")
        return
    print(f"found {len(images)} images; writing to table {MYSQL_CUR_TABLE} and collection {FACE_COLLECTION_NAME}")

    clients = await create_clients()
    added = skipped = 0
    try:
        for offset, image_path in enumerate(images):
            person = generate_person(start_id + offset, image_path)
            try:
                embedding = await enroll.embed_face(image_path)
                await persons.insert_person(clients.mysql, MYSQL_CUR_TABLE, person)
                await vectors.insert_vector(
                    clients.milvus, FACE_COLLECTION_NAME, person.id, embedding.tolist()
                )
                added += 1
            except (AppError, faces.FaceError) as excep:
                # One unusable image must not stop the load.
                skipped += 1
                print(f"skip {image_path}: {excep}")
        await clients.milvus.flush(FACE_COLLECTION_NAME)
    finally:
        await close_clients(clients)

    print(f"added {added}, skipped {skipped}, of {len(images)} images")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_dir", help="directory of face images, one face per image")
    parser.add_argument("--start-id", type=int, default=1, help="first person id to assign")
    args = parser.parse_args()
    asyncio.run(load(args.image_dir, args.start_id))


if __name__ == "__main__":
    main()
