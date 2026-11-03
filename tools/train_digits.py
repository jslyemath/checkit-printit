r"""Train the handwritten-digit recogniser and write `data/digits.npz`.

Run this only to regenerate the recogniser. Nothing in the tool calls
it, and the file it produces is committed -- this exists so that the
372KB of numbers in `src/checkit_printit/data/digits.npz` is something
anybody can reproduce rather than something that turned up one day.

    python tools/train_digits.py

It needs numpy and Pillow, which `scans` needs anyway, and about forty
seconds. The training data is MNIST, downloaded on first run to a
cache **outside** the repository (`~/.cache/checkit-printit/mnist`, or
`%LOCALAPPDATA%` on Windows); it is 11MB and is not committed.

### Why one hidden layer

A convolutional net would score better on MNIST and it would not
matter. The job here is smaller than reading digits in general: a grid
only has to be told apart from the students the record says could have
written it, whose ids differ in at least two places and usually three
or four. Getting eight digits of nine right is enough to land on one
student. See `digits.py` for the measurements.

So the effort went into how a cell is *presented* -- see
`digits.to_mnist` -- and the model stayed something whose inference is
a matrix multiply. That is what keeps this feature from adding a
dependency: numpy was already needed to read a scan at all.

### Why the training data is bent about

MNIST's digits were drawn with a thick stroke, centred, upright. A
student's digit, written in a 4.4mm box in whatever pen was to hand,
photocopied, rasterised at 200dpi and resampled up, is none of those
things. Each minibatch is therefore turned, scaled, shifted, and --
the one that matters most -- had its strokes thickened or thinned,
because stroke width is the difference between MNIST and a 0.5mm pen
and a net that has only seen thick strokes reads a thin one as a
different shape.

One transform per minibatch rather than per image, so the sampling is
a gather instead of a loop. Four hundred and sixty-nine batches an
epoch over fourteen epochs is six thousand different transforms,
which is diversity enough.
"""

import gzip
import os
import pathlib
import sys
import time
import urllib.request

import numpy

#: Where MNIST is fetched from. The canonical home at yann.lecun.com
#: has been unreliable for years; this is the mirror PyTorch uses.
MIRROR = "https://ossci-datasets.s3.amazonaws.com/mnist/"
FILES = ("train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz",
         "t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz")

HIDDEN = 128
BATCH = 128
EPOCHS = 14
RATE = 0.2
DECAY = 1e-4
MOMENTUM = 0.9
SEED = 7


def cache():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    path = pathlib.Path(base) / "checkit-printit" / "mnist"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch():
    """MNIST, downloading it the first time. Returns the folder."""
    folder = cache()
    for name in FILES:
        target = folder / name
        if target.exists():
            continue
        print(f"  fetching {name} from {MIRROR}")
        urllib.request.urlretrieve(MIRROR + name, target)
    return folder


def idx(path):
    """One IDX file as an array.

    The format is two zero bytes, a type byte, a count of dimensions,
    then one big-endian 32-bit length per dimension, then the data.
    """
    raw = gzip.decompress(path.read_bytes())
    dims = raw[3]
    shape = [int.from_bytes(raw[4 + 4 * i:8 + 4 * i], "big")
             for i in range(dims)]
    return numpy.frombuffer(
        raw[4 + 4 * dims:], dtype=numpy.uint8).reshape(shape)


def grid(angle, scale, dx, dy, size=28):
    """Where each output pixel reads from, for one affine transform.

    Built output-to-input, which is the direction that leaves no
    holes.
    """
    middle = (size - 1) / 2
    ys, xs = numpy.meshgrid(numpy.arange(size) - middle,
                           numpy.arange(size) - middle, indexing="ij")
    cos, sin = numpy.cos(angle), numpy.sin(angle)
    return ((cos * xs + sin * ys) / scale + middle - dx,
            (-sin * xs + cos * ys) / scale + middle - dy)


def warp(batch, sx, sy):
    """Sample `batch` at those coordinates, bilinearly."""
    size = batch.shape[-1]
    x0 = numpy.floor(sx).astype(int)
    y0 = numpy.floor(sy).astype(int)
    fx, fy = sx - x0, sy - y0
    out = numpy.zeros_like(batch)
    for ox in (0, 1):
        for oy in (0, 1):
            inside = ((x0 + ox >= 0) & (x0 + ox < size) &
                      (y0 + oy >= 0) & (y0 + oy < size))
            weight = (fx if ox else 1 - fx) * (fy if oy else 1 - fy)
            out += batch[:, numpy.clip(y0 + oy, 0, size - 1),
                         numpy.clip(x0 + ox, 0, size - 1)] * (weight * inside)
    return out


def morph(batch, amount):
    """Thicken (`amount` > 0) or thin (< 0) the strokes.

    By blending towards the largest or smallest of each pixel's four
    neighbours, which is a dilation and an erosion without needing
    either word or a library that has them.
    """
    if not amount:
        return batch
    stack = numpy.stack(
        [batch] + [numpy.roll(batch, step, axis=axis)
                   for axis, step in ((1, 1), (1, -1), (2, 1), (2, -1))])
    other = stack.max(axis=0) if amount > 0 else stack.min(axis=0)
    return numpy.clip(batch * (1 - abs(amount)) + other * abs(amount), 0, 1)


def forward(params, x):
    w1, b1, w2, b2 = params
    hidden = numpy.maximum(0.0, x @ w1 + b1)
    return hidden, hidden @ w2 + b2


def main():
    folder = fetch()
    train_x = idx(folder / FILES[0]).astype(numpy.float32) / 255.0
    train_y = idx(folder / FILES[1]).astype(int)
    test_x = idx(folder / FILES[2]).astype(numpy.float32) / 255.0
    test_y = idx(folder / FILES[3]).astype(int)
    flat_test = test_x.reshape(len(test_x), -1)
    print(f"{len(train_x)} to train on, {len(test_x)} to test on")

    rng = numpy.random.default_rng(SEED)
    params = [rng.normal(0, numpy.sqrt(2 / 784), (784, HIDDEN)),
              numpy.zeros(HIDDEN),
              rng.normal(0, numpy.sqrt(2 / HIDDEN), (HIDDEN, 10)),
              numpy.zeros(10)]
    vels = [numpy.zeros_like(p) for p in params]

    started = time.time()
    for epoch in range(EPOCHS):
        order = rng.permutation(len(train_x))
        rate = RATE * (0.5 ** (epoch / 5))
        for start in range(0, len(order) - BATCH + 1, BATCH):
            pick = order[start:start + BATCH]
            sx, sy = grid(rng.normal(0, 0.14), rng.uniform(0.88, 1.12),
                          rng.uniform(-2, 2), rng.uniform(-2, 2))
            batch = morph(warp(train_x[pick], sx, sy),
                          rng.uniform(-0.6, 0.6))
            x = batch.reshape(len(pick), -1)

            hidden, out = forward(params, x)
            out -= out.max(axis=1, keepdims=True)
            p = numpy.exp(out)
            p /= p.sum(axis=1, keepdims=True)
            p[numpy.arange(len(pick)), train_y[pick]] -= 1
            p /= len(pick)

            back = (p @ params[2].T) * (hidden > 0)
            grads = (x.T @ back + DECAY * params[0], back.sum(axis=0),
                     hidden.T @ p + DECAY * params[2], p.sum(axis=0))
            for param, vel, grad in zip(params, vels, grads):
                vel *= MOMENTUM
                vel -= rate * grad
                param += vel
        right = (forward(params, flat_test)[1].argmax(axis=1) == test_y)
        print(f"  epoch {epoch + 1:>2}: MNIST test {right.mean():.4f}"
              f"   ({time.time() - started:.0f}s)")

    out = (pathlib.Path(__file__).parent.parent
           / "src" / "checkit_printit" / "data" / "digits.npz")
    out.parent.mkdir(parents=True, exist_ok=True)
    numpy.savez_compressed(
        out, **{name: value.astype(numpy.float32)
                for name, value in zip(("w1", "b1", "w2", "b2"), params)})
    print(f"\nwrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
