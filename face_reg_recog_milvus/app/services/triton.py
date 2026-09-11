"""
Triton gRPC transport.

The client is thread safe and cheap to hold, so it is created once and cached here,
together with the model metadata. Building it per request would add three round trips
to every inference.

The client is synchronous on purpose. Its caller is the face pipeline, which runs in
a worker thread (see app.services.enroll.embed_face), and a worker thread has no
event loop for an async client to use.
"""

import contextlib
import logging
from functools import lru_cache

import numpy as np
import tritonclient.grpc as grpcclient

from app.config import TRITON_SERVER_HOST, TRITON_SERVER_PORT

logger = logging.getLogger("triton_client")


@lru_cache(maxsize=1)
def get_client() -> grpcclient.InferenceServerClient:
    """One shared Triton client for the process."""
    url = f"{TRITON_SERVER_HOST}:{TRITON_SERVER_PORT}"
    logger.info("creating triton grpc client for %s", url)
    return grpcclient.InferenceServerClient(url=url)


@lru_cache(maxsize=16)
def _metadata(model: str):
    """Model metadata, fetched once per model instead of once per request."""
    return get_client().get_model_metadata(model_name=model)


def output_names(model: str) -> tuple[str, ...]:
    """Output tensor names for `model`."""
    return tuple(o.name for o in _metadata(model).outputs)


def input_name(model: str) -> str:
    """Sole input tensor name. These models are exported with numeric node names
    ('input.1', 'data', 'images'), so never hardcode them -- ask the server."""
    return _metadata(model).inputs[0].name


def infer(model: str, feeds: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Run `model` on `feeds` ({input_name: array}) and return {output_name: array}."""
    inputs = []
    for name, array in feeds.items():
        tensor = grpcclient.InferInput(name, array.shape, "FP32")
        tensor.set_data_from_numpy(array.astype(np.float32))
        inputs.append(tensor)

    names = output_names(model)
    requested = [grpcclient.InferRequestedOutput(n) for n in names]
    response = get_client().infer(model_name=model, inputs=inputs, outputs=requested)
    return {n: response.as_numpy(n) for n in names}


def is_ready(model: str) -> bool:
    try:
        return get_client().is_model_ready(model_name=model)
    except Exception:
        return False


def close() -> None:
    """
    Close the cached client and forget it.

    Without this, the client is only reclaimed by __del__ during interpreter shutdown,
    by which point grpc's module globals may already be torn down -- which surfaces as
    a spurious "AttributeError: 'NoneType' object has no attribute 'StatusCode'"
    traceback after the process has otherwise finished cleanly.
    """
    if get_client.cache_info().currsize:
        with contextlib.suppress(Exception):
            get_client().close()
    get_client.cache_clear()
    _metadata.cache_clear()
