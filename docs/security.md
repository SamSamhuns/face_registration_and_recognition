# Security notes

Background material on attacking and protecting a face recognition system. None of
this is implemented by the service. It records what the threats are and which
countermeasures exist.

> The API has no authentication. Do not put it on an untrusted network without a
> gateway in front of it.

## Attacks

**Presentation attacks** happen in front of the camera, before any software sees the
face.

- 2D spoofing: a printed photograph, a face shown on a phone or monitor, or a video
  of the victim played back to the camera.
- 3D spoofing: a moulded face mask.

**Indirect attacks** happen after the image is already in the system, at the database
level. Normal information security controls apply to these.

## Countermeasures

Hardware and interaction:

- Stereo depth, 3D face structure, or 3D landmark detection.
- Liveness detection, for example eye blink detection.
- Challenge and response: ask the person to nod, smile or turn the head.
- Context: look for a hand holding a phone or a photograph.

Algorithms:

- Texture analysis. Find the artifacts a screen leaves behind, such as Moire
  patterns, or use Local Binary Patterns.
- Specular features. Train an SVM on specular projections of genuine and spoofed
  faces.
- Frequency analysis. Examine the face in the Fourier domain.
- Optical flow. Flow from a 3D object differs from flow from a flat plane.
- Image quality. Several quality measures together separate a spoof from a genuine
  capture.
- Depth feature fusion. Fuse colour features with a CNN and SENet structure.
- Neural classifiers trained on a large set of genuine and spoofed faces.

`scripts/train_spoofed_face_vector_clsf.py` holds a train and test example for a real
against spoofed classifier.

### Datasets for genuine against spoofed faces

- NUAA Photograph Imposter Database
- [Small set of real and fake face images](https://github.com/SkyThonk/real-and-fake-face-detection)
- [Kaggle real and fake face detection data](https://www.kaggle.com/datasets/ciplab/real-and-fake-face-detection)
- [Deep face detection](https://github.com/selimsef/dfdc_deepfake_challenge)

## Encrypting the stored vectors

A face embedding is not anonymous. A face can be reconstructed from one. See
[reversing face embeddings](https://edwardv.com/cs230_project.pdf).

[Pyfhel](https://pyfhel.readthedocs.io/en/latest/index.html) supports the BGV, BFV
and CKKS homomorphic encryption schemes. Addition, multiplication, exponentiation and
scalar product run directly on the encrypted vectors, and give the same result as the
same operations on the plain vectors.

This allows the vectors to live in a zero-trust database or with an untrusted vendor.
Only the client holds the private key, while the server can still compute distances.

`scripts/homomorphic_emb_face_search_knn.py` holds a client and server example that
finds the closest embeddings with KNN.
