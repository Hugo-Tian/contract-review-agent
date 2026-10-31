"""Generate entirely fictional Hong Kong tenancy fixtures, not real agreements.

Every name, address, amount and transaction below is invented. The leases deliberately
contain common problems (heavy early-termination penalty, no deposit return date,
all repairs on the tenant, unclear outgoings, payee different from the landlord,
no mention of the owner's consent to sublet) so the tools have something to find.
"""
import io
import random
from pathlib import Path
import pymupdf
from docx import Document
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'examples' / 'hk'
FONTS = Path('C:/Windows/Fonts')

LEASE_EN = [
    'FICTIONAL SAMPLE - NOT A REAL AGREEMENT. All names, addresses, amounts and transactions are fictional.',
    'TENANCY AGREEMENT',
    'Date: 15 November 2026',
    'Landlord: Harbour Example Holdings Limited (the "Landlord")',
    'Tenant: Lam Example Student (the "Tenant")',
    'Estate Agent: Example Realty Agency (fictional agency)',
    'Premises: Flat X, 12/F, Example Mansion, 8 Fictional Road, Hong Kong, together with the furniture and appliances listed in the Schedule.',
    '1. Term: 24 months from 1 December 2026 to 30 November 2028. The first 12 months are fixed (the "fixed term").',
    '2. Rent: HK$12,000 per month, payable in advance on the 1st day of each calendar month by bank transfer to the account of Mr. Chan Example Agent.',
    '3. Deposit: The Tenant shall pay a deposit of HK$24,000 (two months\' rent). The deposit shall be returned without interest after the Tenant has delivered vacant possession of the Premises and after deduction of any sums due to the Landlord.',
    '4. Outgoings: The Tenant shall pay water, electricity and gas charges. Rates, Government rent and management fees shall be paid as agreed between the parties.',
    '5. Repairs: The Tenant shall keep the interior of the Premises, including all furniture, fixtures and appliances, in good repair and shall be responsible for all repairs, whether minor or major, except structural repairs.',
    '6. Early termination: If the Tenant terminates this Agreement during the fixed term, the Tenant shall forfeit the deposit and shall in addition pay the rent for the remainder of the fixed term.',
    '7. After the fixed term, either party may terminate this Agreement by giving two months\' written notice.',
    '8. The Tenant shall not assign, sublet or part with possession of the Premises.',
    '9. The Landlord may enter the Premises at reasonable times to inspect, upon prior notice.',
    '10. If the Landlord sells the Premises, the Tenant shall allow viewing at reasonable times.',
    '11. Stamp duty on this Agreement shall be borne by the Landlord and the Tenant in equal shares.',
    '12. The Tenant shall pay commission to the Estate Agent as agreed separately.',
    '13. On expiry or termination, the Tenant shall deliver up the Premises in the same condition as at the commencement of the tenancy, fair wear and tear excepted.',
    'Schedule: List of furniture and appliances - to be attached. (Not attached to this fictional sample.)',
]

# Differs from LEASE_EN on purpose: deposit return within 14 days, landlord repairs appliances.
TEMPORARY_EN = [
    'FICTIONAL SAMPLE - NOT A REAL AGREEMENT. All names, addresses, amounts and transactions are fictional.',
    'PROVISIONAL TENANCY AGREEMENT',
    'Date: 1 November 2026',
    'Landlord: Harbour Example Holdings Limited',
    'Tenant: Lam Example Student',
    'Premises: Flat X, 12/F, Example Mansion, 8 Fictional Road, Hong Kong.',
    '1. Term: 24 months from 1 December 2026. The first 12 months are fixed.',
    '2. Rent: HK$12,000 per month, payable on the 1st day of each month.',
    '3. Deposit: HK$24,000 (two months\' rent), to be refunded within 14 days after the Tenant delivers vacant possession.',
    '4. Initial deposit: HK$5,000 paid on signing this provisional agreement, to form part of the deposit.',
    '5. The Landlord shall be responsible for repairing the air-conditioner, refrigerator and washing machine provided in the Premises, unless the damage is caused by the Tenant.',
    '6. After the fixed term, either party may terminate by giving two months\' written notice.',
    '7. A formal tenancy agreement shall be signed on or before 15 November 2026.',
]

SUBLET_ZH = [
    '虛構示例－並非真實合約。所有名稱、地址、金額及交易均屬虛構。',
    '分租協議（房間）',
    '日期：2026年11月20日',
    '出租人（二房東）：何虛構',
    '承租人：李示例同學',
    '物業：香港虛構道8號示例大廈12樓X室其中一間房（下稱「該房間」），與其他住客共用廚房及浴室。',
    '一、租期：由2026年12月1日起計12個月，全期為死約。',
    '二、租金：每月港幣6,500元，於每月5日前以現金或轉數快支付予何虛構之胞弟何示例。',
    '三、按金：港幣13,000元（兩個月租金），租約期滿後退還。',
    '四、水電煤及上網費用由各住客平均分擔，計算方法由出租人決定。',
    '五、房間內所有家具及電器如有損壞，不論原因，均由承租人負責維修或賠償。',
    '六、承租人如於租期內提前遷出，須繳付餘下租期全部租金，按金不予退還。',
    '七、出租人可隨時進入該房間檢查。',
    '八、承租人遷出時須將該房間回復原狀並交吉。',
    '九、本協議無須加蓋印花。',
]

# What the user says the agent told them; for the landlord/agent promise tool.
AGENT_MESSAGES = [
    '家電壞咗業主會包修。',
    '住滿一年之後，提前一個月通知就可以退租。',
    '退租後7日內全數退回按金。',
    '管理費同差餉由業主負責。',
]

FILES = {'fictional-hk-lease-en': LEASE_EN, 'fictional-hk-temporary-en': TEMPORARY_EN, 'fictional-hk-sublet-zh': SUBLET_ZH}


def write_docx(path, lines):
    word = Document()
    for line in lines:
        word.add_paragraph(line)
    word.save(path)


def write_pdf(path, lines, chinese):
    pdf = pymupdf.open()
    page = pdf.new_page()
    font = 'china-t' if chinese else 'helv'
    rect = pymupdf.Rect(45, 45, page.rect.width - 45, page.rect.height - 45)
    spare = page.insert_textbox(rect, '\n'.join(lines), fontname=font, fontsize=10.5 if chinese else 9.5, lineheight=1.45)
    if spare < 0:
        raise ValueError(f'{path.name}: text does not fit on one page')
    pdf.save(path)
    pdf.close()


def wrap(draw, line, font, width):
    """Wrap by characters for Chinese and by words for English."""
    tokens = list(line) if any('\u4e00' <= ch <= '\u9fff' for ch in line) else line.split(' ')
    sep = '' if tokens == list(line) else ' '
    rows, current = [], ''
    for token in tokens:
        candidate = current + (sep if current else '') + token
        if draw.textlength(candidate, font=font) > width and current:
            rows.append(current)
            current = token
        else:
            current = candidate
    return rows + [current]


def render_scan(lines, font_file, size, seed):
    """A plain page photographed slightly crooked: small rotation, blur and paper noise."""
    width, height, margin = 1654, 2339, 110  # A4 at 200 dpi
    image = Image.new('L', (width, height), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONTS / font_file), size)
    y = margin
    for line in lines:
        for row in wrap(draw, line, font, width - 2 * margin):
            draw.text((margin, y), row, font=font, fill=20)
            y += int(size * 1.6)
        y += int(size * 0.4)
    rng = random.Random(seed)
    image = image.rotate(0.7, resample=Image.BICUBIC, fillcolor=255).filter(ImageFilter.GaussianBlur(0.7))
    pixels = image.load()
    for _ in range(width * height // 60):
        x, yy = rng.randrange(width), rng.randrange(height)
        pixels[x, yy] = max(0, min(255, pixels[x, yy] + rng.randint(-70, 70)))
    return image.convert('RGB')


def save_scan(stem, image):
    image.save(OUT / f'{stem}.png', optimize=True)
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=80)
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buffer.getvalue())
    pdf.save(OUT / f'{stem}.pdf')
    pdf.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, lines in FILES.items():
        chinese = stem.endswith('-zh')
        (OUT / f'{stem}.txt').write_text('\n'.join(lines), encoding='utf-8')
        write_docx(OUT / f'{stem}.docx', lines)
        write_pdf(OUT / f'{stem}.pdf', lines, chinese)
    (OUT / 'fictional-hk-agent-messages.txt').write_text(
        '虛構示例：用戶記錄的代理口頭說法，用於業主／代理承諾對照。\n' + '\n'.join(AGENT_MESSAGES), encoding='utf-8')
    save_scan('fictional-hk-scan-sublet-zh', render_scan(SUBLET_ZH, 'msjh.ttc', 40, seed=7))
    save_scan('fictional-hk-scan-lease-en', render_scan(LEASE_EN[:13], 'arial.ttf', 34, seed=11))
    print('Created fictional HK leases (txt/docx/pdf), agent messages and two scans in', OUT)


if __name__ == '__main__':
    main()
