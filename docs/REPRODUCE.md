# 重现本次运行

本项目按九个官网节目册独立采集，并参考 AI-Paper-Trends 的研究问题，未复制其实现或继承历史数量。

## 环境

Python 3.12。正式依赖写在 pyproject.toml。较快的详情采集可安装 fast-http 可选依赖；没有它时回退至标准库，采集口径不变。语义依赖仅需 ONNX Runtime 和 tokenizers，不需要 Torch。

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r docs/requirements.lock.txt
python -m pip install -e '.[semantic,fast-http]'
python scripts/run.py --help
```

本次受管环境使用已有科学计算运行时，并把新增依赖安装在项目 `.deps` 中。普通重现环境使用上述 venv 即可，不需要保留 `.deps`。执行阶段前应设置 `ORT_DISABLE_TELEMETRY=1`。程序在首次 import ONNX Runtime 前设置同一变量，并调用 `disable_telemetry_events()`；若运行进程已经未按 guard 初始化过 ONNX Runtime，会要求新进程。

## 完整命令

```bash
python scripts/run.py --config configs/latest.json --output output collect
python scripts/run.py --config configs/latest.json --output output prepare
python scripts/run.py --config configs/latest.json --output output backfill
python scripts/run.py --config configs/latest.json --output output prepare --with-details
python scripts/run.py --config configs/latest.json --output output model --backend lsa
ORT_DISABLE_TELEMETRY=1 python scripts/run.py --config configs/semantic.json --output output model --backend onnx
python scripts/compare_models.py --output output
python scripts/run.py --config configs/latest.json --output output analyze --backend lsa
python scripts/run.py --config configs/semantic.json --output output analyze --backend onnx
python scripts/run.py --config configs/semantic.json --output output report --backend onnx
python scripts/run.py --config configs/latest.json --output output validate
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir dist/wheels
python scripts/build_release.py --output output --dist dist
```

最终报告会显示生成时已存在的验证结果。首次报告后 validate，再次 report、validate，可以使报告包含上一轮验证摘要；本轮实际状态以外部 validation.json 和 release_manifest.json 为准，避免报告自包含自身哈希的循环。

## 模型文件

语义模型：sentence-transformers/all-MiniLM-L6-v2，固定 revision：

`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`

| 文件 | SHA256 |
| --- | --- |
| tokenizer.json | be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037 |
| onnx/model_quint8_avx2.onnx | b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21 |

官方文件地址遵循 `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/<revision>/<file>`。首次运行按固定地址下载并验证，元数据保存在 output/model_assets；发行包不重分发权重。若复用缓存，要求元数据 URL 与文件 SHA256 同时一致，不把改名的其他模型当成 MiniLM。

标题和摘要的所有 token 都分块编码，不截去后半篇摘要。每块 attention-mask 均值池化，按内容 token 数加权合并，再 L2 归一化。模型 manifest 记录分块、缓存指纹、参数、种子、版本及输入哈希。所有会议和年份共同拟合；topic_id 只在单一模型内部有意义。两个模型的数字主题不能直接对齐，对照使用相同 paper_id 的 ARI/AMI。

## 断点与不可混用的数据

成功 HTTP 响应采用 gzip 原文及 SHA256，并在本次运行中复用；失败响应不作成功缓存。重抓须另建日期目录，不静默覆盖原快照。不同采集范围或 HTTP 配置写入同一目录会报错；已完成模型输入/参数变化也必须另建目录或保留旧模型目录后再运行。

详情每25条写入 attempts、patches、summary；成功原文先落盘，意外中断后可从 HTTP 缓存重建。相同URL的地点形式归一，不把跨地点展示当新论文。原始批量事件保留重复展示，清洗后的论文只保守合并。部分官网oral链接的 `YYYY-Oral--...` 是展示占位ID，不用作真实OpenReview forum。

OpenReview 403/平台验证会持久化阻断状态，同一运行不得重试或通过其他API版本绕过。本次 reviews 为空，评分和主题条件录用率不可计算。恢复公开评审需要在另一个明确授权的新运行中重新验证可访问性；清除状态文件不是本项目推荐的恢复手段。

三种数据分别使用：官网录用成果语料、带原分母的官方规模统计、公开投稿/评审样本。不能从当前只收录录用论文的语料推断主题接收率。统计口径及来源冲突见 OFFICIAL_SOURCES.md。

## 离线重建

解压 source_complete.zip 作为项目目录，再把 data_and_results.zip 解压到项目的 output/。不发起网络请求也可 prepare --with-details、analyze、report、validate。重新训练 LSA 不需要下载模型。重新训练 ONNX 首次需上述固定权重；缓存向量和预训练文件不是同一内容。

HTML报告内嵌全量CSV/JSONL和分析表，统计基于全量。浏览样本按会议/年份/赛道分层，最多5000行。导出按钮首先在浏览器本地尝试解压，浏览器不支持本地解压时保留gzip下载；页面不依赖CDN或远程服务。

对于临时网络失败或已公开摘要此前为空的条目，可运行 `backfill --retry-failed`。旧失败写入attempts_history，平台验证和身份冲突仍保持终态；已有计划及成功补丁在prepare之后再次backfill时也不被删除。

最终data_and_results.zip保留原始响应、清洗前后语料、逐模型语料/向量/统计和审计记录。单文件report.html独立交付；可复用的SQLite语义缓存与编码断点独立在semantic_encoding_checkpoint.zip交付，最终包不重复塞入相同的稠密预编码矩阵。若需加速重跑，将编码检查点中的output/cache解压到项目相同目录即可。

本轮额外浏览器实交互检查未执行：运行环境无浏览器引擎，尝试安装返回无效/截断ZIP。未将此记为通过。计划要求的静态JavaScript语法、HTML/URL逃逸及全量内嵌下载还原检查已通过；浏览器状态另见output/browser_check.json。
