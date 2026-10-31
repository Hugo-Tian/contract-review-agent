"""Hong Kong residential tenancies. Stage ①: profile skeleton only.

The model prompts (stage ③), HK redaction rules (stage ③), the eLegislation
library (stage ②) and the deposit tool (stage ④) are not in place yet. Until
then live model calls are refused instead of silently using mainland prompts.
"""
import re
from .base import Profile, ContextOptions
from . import cn

FACT_LABELS = ('出租人及身份', '承租人', '收款主体', '物业与范围', '租金与付款', '按金与退还', '租期与提前终止', '费用分担', '维修责任', '分租转租与交还单位')

# Entirely fictional placeholder; the full fictional HK leases arrive in stage ⑤.
SAMPLE = 'FICTIONAL SAMPLE ONLY | Tenancy Agreement (all names, addresses and transactions are fictional)\n1. Landlord: Harbour Example Ltd. Tenant: the fictional student tenant. Premises: Flat X, Example Mansion, Fictional Road, Hong Kong.\n2. Term: 24 months from 1 December 2026. The first 12 months are fixed. Monthly rent HK$12,000 payable on the 1st day of each month.\n3. Deposit: HK$24,000, refundable after the Tenant delivers vacant possession.\n4. The Tenant shall be responsible for all repairs to the Premises and the appliances.\n5. If the Tenant terminates within the fixed term, the Tenant shall pay the rent for the remainder of the term.\n6. Rent shall be paid to the account of Mr. Example Agent.'

UI = {
    **cn.UI,
    'audience': '香港住宅租约',
    'intro': '把租期、按金、费用分担和口头承诺，放回原文里看。',
    'intro_points': ['租多久、怎么退', '按金怎么退', '还需问什么'],
    'intro_disclaimer': '辅助阅读与沟通，不构成法律意见，不判断业主身份、合约效力或扣费是否合法。',
    'fact_display': {label: label for label in FACT_LABELS},
    'context_labels': {'role': '你的身份', 'goal': '这次想了解', 'signed': '是否已签临约或租约', 'paid': '是否已付订金或按金', 'amount': '已付金额（港元）', 'signed_date': '签约日期', 'paid_date': '付款日期', 'services': '目前的情况', 'preferences': '其他背景'},
    'context_placeholders': {'services': '例如：已签临时租约并付细订；还没入住；业主说家电坏了包修。', 'preferences': '例如：人在内地，预计9月到港；想住满一年后提前退租。请勿填写不必要的个人信息。'},
    'sample': SAMPLE,
    'workflow_promise_label': '业主或代理说过的话（可选，每行一条）',
    'workflow_promise_placeholder': '例如：家电坏了业主包修；住满一年可以提前一个月通知退租。请先去除个人信息。',
    'task_plan': '任务计划：分析租约并核验引用 → 有业主或代理说法时逐条对照 → 检索法规参考 → 列出需你确认的下一步。',
    'consent': '我同意发送脱敏正文、所填背景和业主/代理说法，用于本次租约阅读与承诺对照。',
    'capabilities': '香港版仍在开发：真实模型分析、香港法规库和按金试算尚未完成，目前只能使用演示模式查看界面。',
    'next_steps': '使用页面上方工具，把业主或代理说过的话与租约逐条对照，比较临时租约与正式租约。需要下次继续阅读，请手动保存到报告历史。',
    'channels': ['WhatsApp', '微信', '电邮'],
    'tool_names': {**cn.UI['tool_names'], '承诺': '业主 / 代理承诺对照'},
    'promise': {**cn.UI['promise'], 'heading': '业主或代理说了什么，租约有没有写？',
                'intro': '每行一条。聊天截图可以先提取文字，再手动整理。这里只比较说法，不核实业主或代理身份，也不判断截图真伪。',
                'need_doc': '请先导入并核对租约，再对照业主或代理的说法。', 'source_label': '说法来源', 'source_placeholder': '例如：10月20日代理WhatsApp聊天',
                'import_label': '导入聊天截图或资料', 'input_label': '业主或代理说过的话（每行一条，最多30条）', 'input_placeholder': '例如：家电坏了业主包修。请填写对方实际说过的话。',
                'busy': '正在逐条对照业主或代理的说法并核对引用…', 'imported': '已提取资料，请核对OCR文字，并整理为每行一条说法后再对照。', 'default_source': '用户提供的业主或代理说法'},
    'legal': {'default_query': '按金', 'placeholder': '按金、临约、提前退租、差饷、印花税', 'empty': '香港法规库尚未建立，暂时没有可检索条文。'},
}

PROFILE = Profile(
    region='hk', name='香港 · 住宅租约',
    currency={'code': 'HKD', 'unit': '港元'},
    system=None, fact_labels=FACT_LABELS,
    # Stage ③ adds HKID, +852 phone, bank and English name-label rules.
    redact=cn.redact,
    report_forbidden=re.compile(r'https?://|(?:Cap\.?|第)\s*\d+[A-Z]*\s*(?:章|s\.|section)|《[^》]+》第[一二三四五六七八九十百零〇\d]+条|必然无效|一定退款|保证退款|构成诈骗|是骗局|是诈骗', re.I),
    sentence_pattern=cn.PROFILE.sentence_pattern,
    context=ContextOptions(roles=('租客', '准租客', '租客家属'), goals=('签约前检查', '临约与正式租约核对', '入住后核对', '退租与按金')),
    demo={**cn.PROFILE.demo,
          'question': '租约里的费用分担和维修责任能否写清？', 'negotiation': '示例：共同确认费用分担清单，待双方协商。',
          'questions': ['请确认差饷、地租、管理费分别由谁支付。', '请说明按金在退租后多久、按什么标准退还。', '请提供租约提到的全部附件，例如家具家电清单。'],
          'amendments': ['示例：补充按金退还期限和扣减清单，待双方协商。'],
          'message': '您好，签约前想确认几件事：费用分担、按金退还期限和扣减标准，以及租约提到的附件。方便书面说明吗？谢谢。（演示草稿，请按实际情况修改）'},
    promise={**cn.PROFILE.promise, 'system': None,
             'connect_error': '业主/代理承诺对照暂时无法连接模型，请检查网络、密钥或额度后重试。',
             'note': '仅比较你提供的说法与本次正文。引用已核对，解释仍需确认；未核实业主或代理说法的真实性。',
             'consent_error': '请同意发送脱敏租约与业主/代理说法。'},
    legal={'sources': [], 'aliases': {}, 'note': '香港法规库尚未建立（需要从香港电子版法例 eLegislation 获取官方条文）。目前没有可检索的条文。'},
    workflow={'goal_queries': {'退租与按金': '按金 提前退租'}, 'default_query': '租约',
              'promise_step': '业主/代理承诺核验', 'promise_done': '已逐条对照租约；结果见业主 / 代理承诺对照工具。', 'promise_skipped': '未提供业主或代理说法，或当前为演示模式。',
              'final_step': '按金与下一步', 'final_detail': '香港版按金与退租试算尚未完成；系统不猜金额。草稿由你检查后自行发送。'},
    messages={'refund_validation': cn.PROFILE.messages['refund_validation'],
              'not_ready': '香港版的模型提示词尚未完成，暂不能进行真实分析；请先使用演示模式。'},
    ui=UI,
)
