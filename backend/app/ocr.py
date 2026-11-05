"""CPU-only local OCR; recognition never goes online.

Mainland: rapidocr_onnxruntime 1.2.3 with the models bundled in the package (unchanged).
Hong Kong: rapidocr 3.x with PP-OCRv5 server recognition, which reads Traditional Chinese far
better (eval/hk-ocr.md). Its models are fetched once by scripts/fetch_ocr_models.py, SHA-256
checked, into backend/models/ocr; if they are missing, recognition stops instead of downloading.
"""
import io
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from .profiles import current

MODEL_DIR = Path(os.getenv('OCR_MODEL_DIR', Path(__file__).resolve().parents[1] / 'models' / 'ocr'))
V5_FILES = {'Det': 'ch_PP-OCRv4_det_infer.onnx', 'Cls': 'ch_ppocr_mobile_v2.0_cls_infer.onnx', 'Rec': 'ch_PP-OCRv5_rec_server_infer.onnx'}
_engines = {}


def _image_array(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 30000000:
                raise ValueError('图片超过 3000 万像素，请缩小后重试。')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2400, 3200))
            return np.asarray(image)[:, :, ::-1].copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('图片像素过大，请缩小后重试。') from None


def _legacy(array):
    if 'legacy' not in _engines:
        from rapidocr_onnxruntime import RapidOCR
        _engines['legacy'] = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    result, _ = _engines['legacy'](array)
    return [(row[1], float(row[2])) for row in result or ()]


def _ppocr_v5(array):
    if 'v5' not in _engines:
        missing = [name for name in V5_FILES.values() if not (MODEL_DIR / name).is_file()]
        if missing:
            raise ValueError('香港版OCR模型未安装（缺少 ' + '、'.join(missing) + '）。请运行 setup.ps1，或 scripts/fetch_ocr_models.py。')
        from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion
        params = {f'{task}.model_path': str(MODEL_DIR / name) for task, name in V5_FILES.items()}
        params.update({'Rec.lang_type': LangRec.CH, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.SERVER,
                       'Global.log_level': 'error',
                       # On the fictional English scan the angle classifier made whole lines ("3. Deposit …") vanish;
                       # pages are upright (EXIF rotation is applied above), so it is off.
                       'Global.use_cls': False,
                       # Keep low-confidence lines: they are counted in the warning instead of silently dropped.
                       'Global.text_score': 0.0,
                       'EngineConfig.onnxruntime.intra_op_num_threads': int(os.getenv('OCR_THREADS', min(8, os.cpu_count() or 2)))})
        _engines['v5'] = RapidOCR(params=params)
    result = _engines['v5'](array)
    return list(zip(result.txts or (), (float(s) for s in result.scores or ())))


def recognize(data):
    """(text, number of low-confidence lines) for one image."""
    rows = (_ppocr_v5 if current().ocr == 'ppocr-v5-server' else _legacy)(_image_array(data))
    if not rows:
        return '', 0
    return '\n'.join(text for text, _ in rows), sum(score < .85 for _, score in rows)
