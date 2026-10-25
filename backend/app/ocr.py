"""CPU-only local OCR. Model files are bundled with the installed package."""
import io
import numpy as np
from PIL import Image, ImageOps

_engine = None


def recognize(data):
    global _engine
    from rapidocr_onnxruntime import RapidOCR
    if _engine is None:
        _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 30000000:
                raise ValueError('图片超过 3000 万像素，请缩小后重试。')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2400, 3200))
            array = np.asarray(image)[:, :, ::-1].copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('图片像素过大，请缩小后重试。') from None
    result, _ = _engine(array)
    if not result:
        return '', 0
    return '\n'.join(row[1] for row in result), sum(float(row[2]) < .85 for row in result)
