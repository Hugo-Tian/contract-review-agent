"""Build backend/app/legal_corpus_hk.json from official e-Legislation PDFs.

Download each chapter from https://www.elegislation.gov.hk as the bilingual
"Consolidated version for the Whole Chapter (English and Traditional Chinese)" PDF and put
them in one folder, then run from the backend directory:

    ..\\.venv-jiuwen\\Scripts\\python.exe ..\\scripts\\build_hk_legal.py "C:\\path\\to\\folder"

Only the provisions listed in backend/app/profiles/hk.py are kept, copied verbatim.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['REGION'] = 'hk'
os.environ['HK_LEGAL_SOURCE_DIR'] = sys.argv[1]
from app import legal  # noqa: E402

result = asyncio.run(legal.refresh())
for source in result['sources']:
    print(f"{source['id']}: {source['count']} 条" + (f"，{source['error']}" if source['error'] else f"，版本日期 {source['effective']}"))
print('合计', result['count'], '条 →', legal.corpus_path('hk'))
