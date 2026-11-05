"""Put the Hong Kong edition's OCR models in backend/models/ocr, verified by SHA-256.

URLs and hashes come from the manifest shipped inside the installed `rapidocr` package
(default_models.yaml, RapidAI's official ModelScope repository). A file is kept only if its
hash matches. Run from anywhere:

    .venv-jiuwen\\Scripts\\python.exe scripts\\fetch_ocr_models.py [--from FOLDER]

--from copies matching files from a folder that already has them instead of downloading.
"""
import hashlib
import shutil
import sys
from pathlib import Path
import requests
import yaml
import rapidocr

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'backend' / 'models' / 'ocr'
# engine / version / task / file name in RapidOCR's manifest
WANTED = [('PP-OCRv4', 'det', 'ch_PP-OCRv4_det_infer.onnx'),
          ('PP-OCRv4', 'cls', 'ch_ppocr_mobile_v2.0_cls_infer.onnx'),
          ('PP-OCRv5', 'rec', 'ch_PP-OCRv5_rec_server_infer.onnx')]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    manifest = yaml.safe_load((Path(rapidocr.__file__).parent / 'default_models.yaml').read_text(encoding='utf-8'))
    source = Path(sys.argv[sys.argv.index('--from') + 1]) if '--from' in sys.argv else None
    TARGET.mkdir(parents=True, exist_ok=True)
    for version, task, name in WANTED:
        entry = manifest['onnxruntime'][version][task][name]
        url, expected = entry['model_dir'], entry['SHA256']
        target = TARGET / name
        if target.exists() and sha256(target) == expected:
            print(f'ok      {name}')
            continue
        temp = target.with_suffix('.part')
        if source and (source / name).exists():
            shutil.copyfile(source / name, temp)
        else:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with open(temp, 'wb') as f:
                    for chunk in response.iter_content(1 << 20):
                        f.write(chunk)
        actual = sha256(temp)
        if actual != expected:
            temp.unlink()
            raise SystemExit(f'{name}: SHA-256 mismatch ({actual}), file discarded.')
        temp.replace(target)
        print(f'fetched {name} ({target.stat().st_size / 1048576:.1f} MB, SHA-256 verified)')


if __name__ == '__main__':
    main()
