# 香港版 OCR 评测（本机 RapidOCR）

日期：2026-10-31。引擎：`rapidocr_onnxruntime` 1.2.3，随包自带的 `ch_PP-OCRv3` 识别模型（以简体中文和英文为主）。

## 样本

全部为虚构材料，由 `scripts/create_hk_examples.py` 生成，模拟“拍得略歪的打印页”：A4、200 dpi、旋转 0.7°、轻度模糊和噪点。

| 样本 | 内容 |
|---|---|
| `examples/hk/fictional-hk-scan-sublet-zh.png` / `.pdf` | 繁体中文分租协议（二房东），共 369 个非空白字符 |
| `examples/hk/fictional-hk-scan-lease-en.png` / `.pdf` | 英文住宅租约前 13 行，共 1270 个非空白字符 |

复现方法：在 backend 目录运行 `..\.venv-jiuwen\Scripts\python.exe ..\scripts\evaluate_hk_ocr.py`。

## 结果

字符错误率（CER）按去掉空白后的编辑距离计算。这只是 2 份虚构样本上的结果，不代表真实扫描件或手机照片的准确率。

| 文件 | CER | 关键词识别（找到 / 总数） | 主要问题 |
|---|---|---|---|
| 繁体 PNG | 17.9% | 6 / 12 | 繁体被识别成简体（約→约、號→号、廈→厦）；少数字被误认（學→擎、與→舆、兩→雨）；**字典外的繁体字会被直接漏掉** |
| 繁体 PDF | 16.8% | 7 / 12 | 同上 |
| 英文 PNG | 6.6% | 8 / 10 | `HK$` → `HKs`；部分单词之间的空格丢失 |
| 英文 PDF | 6.5% | 7 / 10 | 同上 |

会改变意思的漏字（来自繁体样本）：

- 「港幣6,500元」→「港6,500元」
- 「全期為死約」→「全期死约」
- 「按金不予退還」→「按金不予退」
- 「提前遷出」→「提前出」
- 「兩個月租金」→「雨個月租金」

结论：英文租约基本可用，但金额符号必须核对。**繁体中文识别明显不够可靠**，漏掉的往往正是金额单位、否定词和动词。

## 已采取的措施（不引入新依赖）

- 香港版只要用到了 OCR，就额外显示一条警告，点名上面这些具体错误，提醒用户逐字核对金额、货币、否定词和期限。大陆版的提示不变。
- OCR 文本照旧标记为“请核对”。系统不会自动改写 `HKs` 等疑似错误，以免把猜测当作原文。

## 可在本机运行的替代方案（仅调研，尚未引入）

以下信息来自 RapidOCR 文档和社区模型仓库，**尚未在本机验证**：

1. **RapidOCR 新版 + `chinese_cht` 识别模型**：RapidOCR 的模型列表里有专门的繁体中文识别模型（标注为 PP-OCRv4 系列，支持 onnxruntime），可以通过配置指定识别模型和字典。需要把 `rapidocr_onnxruntime` 1.x 升级到新版 `rapidocr` 包，并下载模型文件（mobile 版通常是十几 MB）。
2. **PP-OCRv5 识别模型**：据第三方说明，一个模型同时支持简体、繁体、英文和日文，有社区转换的 ONNX 版本（例如 `PP-OCRv5_server_rec.onnx` 配 `ppocrv5_dict.txt`）。server 版体积更大，CPU 推理更慢。

建议：先在单独分支试第 1 种。用本目录的评测脚本对比 CER 和关键词识别，同时确认许可证、模型体积和识别速度，再决定是否替换。模型文件的来源和校验值需要人工确认。

参考：

- RapidOCR 模型列表：https://rapidai.github.io/RapidOCRDocs/latest/model_list/
- PP-OCR ONNX 模型（社区转换）：https://huggingface.co/monkt/paddleocr-onnx
