"""向量化 (embedding.py) —— 生成仓库 embedding 用于 LanceDB 向量检索。

策略:
  1. EMBEDDING_API_KEY / OPENAI_API_KEY 存在 -> 调用 API embedding (维度更高)
  2. 否则 -> 本地 TF 哈希嵌入 (384 维, 零依赖, 中英文混合可用)

本地嵌入说明:
  基于字符/词元 hash 的稀疏向量 -> 归一化到 384 维。
  对中英文混合文本有效 (中文按字 bigram, 英文按词), 可支撑语义近似检索
  (如 "需要 RAG 向量检索能力" 与仓库描述含 rag/vector 的记录相似度高)。

生产建议: 配置 OPENAI_API_KEY 或 EMBEDDING_API_URL 使用更强的 embedding 模型。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request

EMBED_DIM = 384

# ============================================================
# 中英术语映射 (跨语言匹配桥接)
# 纯中文需求与英文仓库描述匹配的核心: 把中文术语扩展为英文同义词 token
# ============================================================

ZH_EN_MAP = {
    "量子": ["quantum"],
    "计算": ["compute", "computing", "calculator"],
    "模拟": ["simulate", "simulation", "simulator"],
    "模拟器": ["simulator"],
    "智能": ["intelligence", "ai"],
    "智能体": ["agent"],
    "代理": ["agent", "proxy"],
    "机器人": ["robot", "bot"],
    "知识": ["knowledge"],
    "知识库": ["knowledge-base", "knowledge"],
    "检索": ["retrieval", "search", "index"],
    "向量": ["vector", "embedding"],
    "嵌入": ["embedding", "embed"],
    "数据库": ["database", "db", "sql"],
    "向量库": ["vector-db", "vectordb"],
    "搜索": ["search", "index"],
    "框架": ["framework"],
    "工具": ["tool", "cli"],
    "命令": ["command", "cli"],
    "提示": ["prompt"],
    "提示词": ["prompt"],
    "翻译": ["translate", "translation"],
    "对话": ["chat", "conversation", "dialog"],
    "问答": ["qa", "question"],
    "推理": ["inference", "reason"],
    "训练": ["train", "training"],
    "模型": ["model", "llm"],
    "大模型": ["llm", "model"],
    "文本": ["text", "nlp"],
    "代码": ["code", "coding"],
    "编程": ["coding", "programming"],
    "生成": ["generate", "generation"],
    "图片": ["image"],
    "图像": ["image", "vision"],
    "图像识别": ["image-recognition", "vision", "object-detection"],
    "视觉": ["vision", "visual"],
    "检测": ["detection", "detect", "recognition"],
    "识别": ["recognition", "detect", "ocr"],
    "目标检测": ["object-detection", "detection"],
    "条纹": ["stripe", "pattern"],
    "计算机视觉": ["computer-vision", "vision"],
    "视频": ["video"],
    "音频": ["audio", "speech"],
    "语音": ["speech", "voice", "asr"],
    "工作流": ["workflow", "pipeline"],
    "编排": ["orchestration", "orchestrator"],
    "路由": ["routing", "router"],
    "监控": ["monitor", "observability"],
    "日志": ["log", "logging"],
    "测试": ["test", "testing"],
    "部署": ["deploy", "deployment"],
    "容器": ["container", "docker"],
    "云": ["cloud"],
    "安全": ["security"],
    "爬虫": ["crawler", "spider", "scrape"],
    "抓取": ["crawl", "scrape", "fetch"],
    "文档": ["document", "docs"],
    "文档库": ["docs", "documentation"],
    "分析": ["analy", "analysis"],
    "数据": ["data"],
    "可视化": ["visualization", "visualize", "chart"],
    "图表": ["chart", "graph"],
    "接口": ["api", "sdk"],
    "应用": ["app", "application"],
    "平台": ["platform"],
    "网关": ["gateway"],
    "插件": ["plugin", "extension"],
    "扩展": ["extension", "plugin"],
    "生态": ["ecosystem"],
    "资源": ["resource", "awesome", "list"],
    "索引": ["index", "catalog"],
    "目录": ["catalog", "directory", "list"],
    "压缩": ["compress", "token"],
    "标记": ["token"],
    "token": ["token"],
    "开源": ["open-source", "oss"],
    "协议": ["protocol", "license"],
    "标准": ["standard"],
    "以太坊": ["ethereum", "eth", "web3"],
    "区块链": ["blockchain", "chain", "web3"],
    "交易": ["transaction", "trade", "exchange"],
    "浏览器": ["browser", "explorer"],
    "钱包": ["wallet", "defi"],
    "去中心化": ["decentralized", "defi", "web3"],
    "合约": ["contract", "smart-contract"],
    "比特币": ["bitcoin", "btc"],
    "行情": ["market", "price", "quote"],
    "地图": ["map", "geo", "gis"],
    "电商": ["ecommerce", "shop"],
    "支付": ["payment", "pay"],
    "邮件": ["email", "mail"],
    "短信": ["sms", "message"],
    "通知": ["notification", "notify", "push"],
    "认证": ["auth", "authentication", "login"],
    "登录": ["login", "auth", "sso"],
    "权限": ["permission", "rbac", "acl"],
    "推荐": ["recommend", "recommendation"],
    "协同": ["collaboration", "collaborative"],
    "自动化": ["automation", "auto"],
    "定时任务": ["cron", "scheduler", "schedule"],
    "调度": ["scheduler", "cron", "orchestrator"],
    "队列": ["queue", "mq", "message-queue"],
    "缓存": ["cache", "redis", "caching"],
    "存储": ["storage", "store"],
    "文件": ["file", "filesystem"],
    "上传": ["upload", "multipart"],
    "下载": ["download", "client"],
    "实时": ["realtime", "live", "streaming"],
    "推送": ["push", "websocket", "notification"],
    "消息": ["message", "mq", "kafka"],
    "事件": ["event", "event-driven"],
    "微服务": ["microservice", "micro-services"],
    "分布式": ["distributed", "cluster"],
    "集群": ["cluster", "kubernetes", "k8s"],
    "大数据": ["big-data", "spark", "hadoop"],
    "数据仓库": ["data-warehouse", "olap"],
    "数据管道": ["data-pipeline", "etl"],
    "分类": ["classification", "classify", "categorize"],
    "聚类": ["cluster", "clustering"],
    "预测": ["predict", "prediction", "forecast"],
    "神经网络": ["neural-network", "nn", "deep-learning"],
    "深度学习": ["deep-learning", "neural", "nn"],
    "机器学习": ["machine-learning", "ml"],
    "强化学习": ["reinforcement-learning", "rl"],
    "自然语言": ["nlp", "natural-language"],
    "语音识别": ["speech-recognition", "asr", "stt"],
    "语音合成": ["tts", "speech-synthesis"],
    "人脸": ["face", "facial"],
    "姿态": ["pose", "skeleton"],
    "分割": ["segmentation"],
    "三维": ["3d", "threejs"],
    "渲染": ["render", "rendering"],
    "游戏": ["game", "gaming"],
    "直播": ["live", "streaming", "livestream"],
    "编辑器": ["editor", "ide"],
    "终端": ["terminal", "cli"],
    "命令行": ["command-line", "cli", "terminal"],
    "调试": ["debug", "debugging"],
    "性能": ["performance", "benchmark", "profiling"],
    "优化": ["optimize", "optimization", "tune"],
    "加密": ["encrypt", "crypto", "cryptography"],
    "哈希": ["hash", "hashing"],
    "签名": ["signature", "sign", "jwt"],
    "备份": ["backup", "snapshot"],
    "恢复": ["recovery", "restore"],
    "迁移": ["migration", "migrate"],
    "同步": ["sync", "synchronization"],
    "版本": ["version", "release"],
    "发布": ["release", "publish", "deploy"],
    "构建": ["build", "compile"],
    "编译": ["compile", "compiler"],
    "代码检查": ["lint", "linter", "static-analysis"],
    "文档生成": ["doc-generation", "docs"],
    "API文档": ["api-docs", "swagger", "openapi"],
    "接口测试": ["api-test", "postman"],
    "压力测试": ["load-test", "stress-test", "benchmark"],
    "单元测试": ["unit-test", "unittest", "jest"],
    "日志分析": ["log-analysis", "observability"],
    "可观测": ["observability", "tracing", "metrics"],
    "指标": ["metrics", "telemetry"],
    "追踪": ["tracing", "trace", "apm"],
    "告警": ["alert", "alerting", "alarm"],
    "持续集成": ["ci", "continuous-integration", "github-actions"],
    "持续部署": ["cd", "continuous-deployment"],
    "代码评审": ["code-review", "cr"],
    "许可证": ["license"],
    "合规": ["compliance", "license"],
    "隐私": ["privacy", "gdpr"],
    "报表": ["report", "dashboard", "bi"],
    "仪表盘": ["dashboard", "bi", "metrics"],
    "商业智能": ["bi", "business-intelligence"],
    "电子表格": ["spreadsheet", "excel", "csv"],
    "表格": ["table", "spreadsheet"],
    "SQL": ["sql"],
    "NoSQL": ["nosql", "mongodb"],
    "关系数据库": ["relational-database", "sql", "postgres"],
    "图数据库": ["graph-database", "neo4j"],
    "时序数据库": ["time-series", "tsdb", "influxdb"],
    "搜索引擎": ["search-engine", "elasticsearch"],
    "全文检索": ["full-text", "fts", "search"],
    "推荐系统": ["recommendation", "recommender", "recsys"],
    "风控": ["risk", "risk-control", "fraud"],
    "审批": ["approval", "workflow"],
    "流程": ["workflow", "process", "bpm"],
    "工单": ["ticket", "helpdesk"],
    "客服": ["support", "helpdesk", "crm"],
    "招聘": ["recruit", "hiring", "job"],
    "简历": ["resume", "cv"],
    "医疗": ["healthcare", "medical", "health"],
    "健康": ["health", "wellness"],
    "生物": ["bio", "biology"],
    "基因组": ["genome", "genomics", "dna"],
    "化学": ["chemistry", "chem"],
    "物理": ["physics", "phys"],
    "数学": ["math", "mathematics"],
    "统计": ["statistics", "statistical"],
    "教育": ["education", "learning", "e-learning"],
    "写作": ["writing", "author"],
    "营销": ["marketing", "growth"],
    "内容": ["content", "cms"],
    "媒体": ["media", "multimedia"],
    "新闻": ["news", "feed"],
    "天气": ["weather", "forecast"],
    "旅游": ["travel", "tourism"],
    "物流": ["logistics", "shipping", "delivery"],
    "库存": ["inventory", "stock"],
    "供应链": ["supply-chain", "scm"],
    "物联网": ["iot", "internet-of-things"],
    "嵌入式": ["embedded", "firmware"],
    "硬件": ["hardware", "soc"],
    "芯片": ["chip", "silicon", "semiconductor"],
    "自动驾驶": ["autonomous-driving", "self-driving", "adas"],
    "无人机": ["drone", "uav"],
    "卫星": ["satellite", "space"],
    "航天": ["space", "aerospace", "rocket"],
    "金融": ["finance", "fintech", "trading"],
    "银行": ["bank", "banking"],
    "保险": ["insurance"],
    "证券": ["securities", "stock", "exchange"],
    "股票": ["stock", "equity", "trading"],
    "基金": ["fund", "etf"],
    "量化": ["quant", "quantitative", "trading"],
    "期货": ["futures", "derivatives"],
    "期权": ["option", "options"],
    "债券": ["bond", "fixed-income"],
    "汇率": ["exchange-rate", "forex", "fx"],
    "利率": ["interest-rate", "yield"],
    "经济": ["economy", "economic", "macro"],
    "政策": ["policy", "regulation"],
    "监管": ["regulation", "compliance", "regulatory"],
    "专利": ["patent"],
    "域名": ["domain", "dns"],
    "服务器": ["server", "host"],
    "运维": ["ops", "devops", "sre"],
    "基础设施": ["infrastructure", "infra"],
    "网络": ["network", "networking"],
    "防火墙": ["firewall", "security"],
    "漏洞": ["vulnerability", "cve", "security"],
    "渗透测试": ["pentest", "penetration-testing", "security"],
    "证书": ["certificate", "tls", "ssl"],
    "密钥": ["key", "secret", "crypto"],
    "口令": ["password", "credential"],
    "凭据": ["credential", "secret"],
    "会话": ["session", "cookie"],
    "跨域": ["cors", "cross-origin"],
    "内网穿透": ["tunnel", "ngrok", "reverse-proxy"],
    "CDN": ["cdn", "edge"],
    "边缘计算": ["edge-computing", "edge"],
    "函数计算": ["serverless", "faas", "lambda"],
    "无服务器": ["serverless", "faas"],
    "容器编排": ["container-orchestration", "kubernetes", "k8s"],
    "容器化": ["container", "docker", "kubernetes"],
    "镜像": ["image", "docker", "container"],
    "虚拟机": ["vm", "virtual-machine", "virtualization"],
    "操作系统": ["os", "operating-system", "kernel"],
    "内核": ["kernel", "os"],
    "驱动": ["driver", "kernel"],
    "固件": ["firmware", "embedded"],
    "高可用": ["high-availability", "ha", "failover"],
    "容灾": ["disaster-recovery", "dr", "failover"],
    "性能监控": ["performance-monitoring", "apm", "profiling"],
    "资源监控": ["resource-monitoring", "metrics", "grafana"],
    "网络监控": ["network-monitoring", "snmp", "observability"],
    "应用监控": ["apm", "application-monitoring", "tracing"],
    "链路追踪": ["tracing", "distributed-tracing", "apm"],
    "灰度发布": ["canary", "gray-release"],
    "蓝绿部署": ["blue-green", "deployment"],
    "回滚": ["rollback", "revert"],
    "配置管理": ["config-management", "config"],
    "密钥管理": ["secret-management", "vault", "kms"],
    "身份管理": ["iam", "identity", "sso"],
    "访问控制": ["access-control", "rbac", "acl"],
    "单点登录": ["sso", "single-sign-on", "oauth"],
    "OAuth": ["oauth", "sso"],
    "短信验证": ["sms", "verification", "otp"],
    "邮件验证": ["email", "verification", "otp"],
    "图形验证": ["captcha", "verification"],
    "生物识别": ["biometric", "fingerprint", "face"],
    "指纹": ["fingerprint", "biometric"],
    "文字识别": ["ocr", "text-recognition"],
    "语音转文字": ["asr", "stt", "speech-to-text"],
    "文字转语音": ["tts", "text-to-speech"],
    "机器翻译": ["machine-translation", "mt", "translate"],
    "情感分析": ["sentiment-analysis", "sentiment", "nlp"],
    "意图识别": ["intent-recognition", "intent", "nlp"],
    "实体识别": ["ner", "entity-recognition", "nlp"],
    "关键词提取": ["keyword-extraction", "keywords"],
    "摘要生成": ["summarization", "summary", "abstract"],
    "文本生成": ["text-generation", "generation"],
    "代码生成": ["code-generation", "codegen"],
    "图像生成": ["image-generation", "text-to-image"],
    "视频生成": ["video-generation", "text-to-video"],
    "音频生成": ["audio-generation", "text-to-audio"],
    "对话系统": ["chatbot", "dialogue", "conversation"],
    "聊天机器人": ["chatbot", "bot", "chat"],
    "虚拟人": ["virtual-human", "avatar", "digital-human"],
    "数字人": ["digital-human", "avatar", "virtual-human"],
    "元宇宙": ["metaverse", "vr", "ar"],
    "虚拟现实": ["vr", "virtual-reality"],
    "增强现实": ["ar", "augmented-reality"],
    "3D打印": ["3d-printing", "additive-manufacturing"],
    "激光": ["laser", "lidar"],
    "雷达": ["radar", "lidar", "sensor"],
    "传感器": ["sensor", "iot"],
    "摄像头": ["camera", "vision"],
    "音频处理": ["audio-processing", "dsp", "audio"],
    "视频处理": ["video-processing", "ffmpeg", "video"],
    "图像处理": ["image-processing", "cv", "vision"],
    "信号处理": ["signal-processing", "dsp"],
    "匿名": ["anonymous", "privacy"],
    "网络爬虫": ["web-crawler", "crawler", "scraper"],
    "链接": ["link", "url"],
    "短链接": ["short-url", "shortener"],
    "二维码": ["qr-code", "qr"],
    "条形码": ["barcode", "code"],
    "扫描": ["scan", "scanner"],
    "打印": ["print", "printer"],
    "办公": ["office", "document"],
    "PDF": ["pdf", "document"],
    "演示文稿": ["presentation", "slides", "ppt"],
    "思维导图": ["mindmap", "mind-map"],
    "笔记": ["note", "notes"],
    "剪贴板": ["clipboard", "copy"],
    "快捷键": ["shortcut", "hotkey", "keyboard"],
    "输入法": ["ime", "input-method"],
    "字体": ["font", "typography"],
    "图标": ["icon", "icons"],
    "主题": ["theme", "template"],
    "模板": ["template", "boilerplate", "starter"],
    "脚手架": ["scaffold", "boilerplate", "starter"],
    "前端框架": ["frontend-framework", "react", "vue"],
    "后端框架": ["backend-framework", "fastapi", "django", "spring"],
    "全栈": ["full-stack", "fullstack"],
    "响应式": ["responsive", "mobile"],
    "移动端": ["mobile", "ios", "android"],
    "小程序": ["miniprogram", "wechat", "mini-app"],
    "微信": ["wechat", "weixin"],
    "支付宝": ["alipay", "payment"],
    "第三方登录": ["oauth", "sso", "social-login"],
    "分享": ["share", "social"],
    "秒杀": ["flash-sale", "seckill"],
    "优惠券": ["coupon", "discount", "promotion"],
    "积分": ["points", "reward", "loyalty"],
    "会员": ["membership", "vip", "subscription"],
    "订阅": ["subscription", "subscribe"],
    "付费": ["payment", "billing", "subscription"],
    "账单": ["billing", "invoice", "statement"],
    "计费": ["billing", "metering", "usage"],
    "排行榜": ["leaderboard", "ranking"],
    "头像": ["avatar", "profile"],
    "个人资料": ["profile", "account"],
    "数据导出": ["data-export", "export"],
    "数据导入": ["data-import", "import"],
    "批量处理": ["batch", "bulk"],
    "异步": ["async", "asynchronous"],
    "并发": ["concurrent", "parallel", "multi-thread"],
    "并行": ["parallel", "concurrent"],
    "协程": ["coroutine", "async"],
    "多线程": ["multi-thread", "thread"],
    "多进程": ["multi-process", "process"],
    "内存": ["memory", "ram"],
    "CPU": ["cpu", "processor"],
    "GPU": ["gpu", "cuda", "graphics"],
    "FPGA": ["fpga", "hardware"],
    "量子计算": ["quantum-computing", "quantum"],
    "边缘设备": ["edge-device", "edge"],
    "5G": ["5g", "cellular", "network"],
    "WIFI": ["wifi", "wireless", "network"],
    "蓝牙": ["bluetooth", "ble"],
    "近场通信": ["nfc", "near-field"],
    "射频": ["rf", "radio-frequency"],
    "定位": ["location", "positioning", "gps"],
    "导航": ["navigation", "gps", "map"],
    "出行": ["travel", "transportation", "mobility"],
    "交通": ["traffic", "transportation"],
    "城市": ["city", "urban", "smart-city"],
    "智慧城市": ["smart-city", "urban"],
    "能源": ["energy", "power", "grid"],
    "电力": ["power", "electricity", "grid"],
    "水利": ["water", "hydrology"],
    "农业": ["agriculture", "farming", "agri"],
    "环保": ["environment", "green", "eco"],
    "碳排放": ["carbon", "emission", "climate"],
    "气候": ["climate", "weather"],
    "气象": ["meteorology", "weather", "climate"],
    "地震": ["earthquake", "seismic"],
    "海洋": ["ocean", "marine", "sea"],
    "矿业": ["mining", "mineral"],
    "石油": ["oil", "petroleum", "gas"],
    "天然气": ["gas", "natural-gas"],
    "化工": ["chemical", "chemistry", "process"],
    "材料": ["material", "materials"],
    "纳米": ["nano", "nanotechnology"],
    "半导体": ["semiconductor", "chip", "wafer"],
    "光电子": ["optoelectronics", "photonics", "optical"],
    "光学": ["optics", "optical", "photonics"],
    "量子纠缠": ["entanglement", "quantum"],
    "加密资产": ["crypto-asset", "cryptocurrency", "digital-asset"],
    "加密货币": ["cryptocurrency", "crypto", "coin"],
    "交易所": ["exchange", "dex", "cex"],
    "去中心化金融": ["defi", "decentralized-finance"],
    "稳定币": ["stablecoin", "usdt", "usdc"],
    "跨链": ["cross-chain", "bridge", "interoperability"],
    "智能合约": ["smart-contract", "solidity", "evm"],
    "NFT": ["nft", "non-fungible"],
    "数字藏品": ["nft", "digital-collectible"],
    "代币": ["token", "coin"],
    "公链": ["public-chain", "layer1", "blockchain"],
    "联盟链": ["consortium-chain", "fabric", "blockchain"],
    "链上数据": ["on-chain", "blockchain-data", "indexer"],
    "区块浏览器": ["block-explorer", "explorer", "etherscan"],
    "节点": ["node", "validator", "miner"],
    "挖矿": ["mining", "miner", "pow"],
    "质押": ["staking", "pos", "validator"],
    "共识": ["consensus", "pow", "pos"],
    "分片": ["sharding", "shard"],
    "扩容": ["scaling", "layer2", "rollup"],
    "二层网络": ["layer2", "l2", "rollup"],
    "零知识证明": ["zero-knowledge", "zkp", "zk"],
    "同态加密": ["homomorphic-encryption", "he", "fhe"],
    "多方计算": ["mpc", "multi-party-computation", "secure-computation"],
    "联邦学习": ["federated-learning", "fl"],
    "差分隐私": ["differential-privacy", "dp"],
    "可信计算": ["trusted-computing", "tpm", "tee"],
    "机密计算": ["confidential-computing", "tee", "enclave"],
    "隐私计算": ["privacy-computing", "mpc", "tee"],
    "数据要素": ["data-element", "data-asset"],
    "数据交易": ["data-trading", "data-exchange"],
    "数据确权": ["data-rights", "data-provenance"],
    "数据资产": ["data-asset", "data-element"],
    "数据治理": ["data-governance", "governance", "metadata"],
    "数据质量": ["data-quality", "quality", "profiling"],
    "元数据": ["metadata"],
    "数据血缘": ["data-lineage", "lineage", "metadata"],
    "数据标准": ["data-standard", "standard"],
    "指标体系": ["metric-system", "metrics", "kpi"],
    "维度建模": ["dimensional-modeling", "olap", "star-schema"],
    "实时数仓": ["realtime-warehouse", "clickhouse", "flink"],
    "湖仓一体": ["lakehouse", "delta-lake", "hudi"],
    "流批一体": ["stream-batch", "flink", "unified"],
    "批处理": ["batch-processing", "spark", "mapreduce"],
    "流处理": ["stream-processing", "flink", "kafka-streams"],
    "消息队列": ["message-queue", "kafka", "rabbitmq"],
    "事件驱动": ["event-driven", "event-sourcing", "cqrs"],
    "领域驱动": ["ddd", "domain-driven-design"],
}


# ============================================================
# 文本 -> 词元
# ============================================================

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _zh_aliases(cjk_chars: list[str]) -> list[str]:
    """中文序列 -> 中英别名: 尝试整句/大块匹配, 再逐字 bigram 查表。"""
    aliases: list[str] = []
    text = "".join(cjk_chars)
    # 优先最长匹配 (贪心)
    keys = sorted(ZH_EN_MAP.keys(), key=len, reverse=True)
    rest = text
    i = 0
    while i < len(rest):
        matched = False
        for k in keys:
            if rest.startswith(k):
                aliases.extend(ZH_EN_MAP[k])
                i += len(k)
                rest = rest[len(k):]
                matched = True
                break
        if not matched:
            i += 1
            rest = rest[1:]
    return aliases


def tokenize(text: str) -> list[str]:
    """中英文混合分词: 英文小写单词 + 中文 bigram + 中英别名扩展。"""
    text = text.lower()
    tokens: list[str] = []
    # 英文/数字词
    tokens.extend(_WORD_RE.findall(text))
    # 中文 bigram
    cjk = _CJK_RE.findall(text)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    if len(cjk) == 1:
        tokens.append(cjk[0])
    # 中英别名扩展 (中文术语 -> 英文同义词)
    if cjk:
        tokens.extend(_zh_aliases(cjk))
    return tokens


def _hash_token(token: str, dim: int) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim


def embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """本地 TF hash 嵌入 (无监督, 确定性, 中英桥接)。"""
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for t in tokens:
        vec[_hash_token(t, dim)] += 1.0
    # L2 归一化
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def build_repo_text(repo: dict) -> str:
    """把仓库记录拼接为 embedding 输入文本 (含中文别名扩展)。"""
    parts = [
        repo.get("name", ""),
        repo.get("full_name", ""),
        repo.get("description", "") or "",
        repo.get("description_zh", "") or "",
        repo.get("function_summary", "") or "",
        repo.get("use_case", "") or "",
        " ".join(repo.get("topics", []) or []),
        " ".join(repo.get("function_tags", []) or []),
        repo.get("category", "") or "",
    ]
    text = " ".join(filter(None, parts))
    # 中文别名扩展: 让仓库侧 embedding 也能被中文需求命中
    cjk = _CJK_RE.findall(text)
    if cjk:
        text += " " + " ".join(_zh_aliases(cjk))
    return text


def embed_repo(repo: dict, dim: int = EMBED_DIM) -> list[float]:
    return embed_text(build_repo_text(repo), dim=dim)


# ============================================================
# API 嵌入 (可选, 更高质量)
# ============================================================

def _api_embed(texts: list[str]) -> list[list[float]] | None:
    """调用 OpenAI 兼容 embedding API (可配置)。"""
    key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    url = os.environ.get("EMBEDDING_API_URL", "https://api.openai.com/v1/embeddings")
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        body = json.dumps({"model": model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = [d["embedding"] for d in data.get("data", [])]
        return out or None
    except Exception as e:
        print(f"[embedding] api error, fallback to local: {e}")
        return None


def embed_batch(repos: list[dict], dim: int = EMBED_DIM) -> list[list[float]]:
    """批量嵌入: 优先 API (OpenAI 兼容 / Ollama), 失败/无 key 回退本地。"""
    texts = [build_repo_text(r) for r in repos]
    api = _api_embed(texts)
    if api and len(api) == len(texts):
        return api
    ollama = _ollama_embed(texts)
    if ollama and len(ollama) == len(texts):
        return ollama
    return [embed_text(t, dim=dim) for t in texts]


# Ollama 不可用缓存 (避免每次 embed_batch 都等超时)
_OLLAMA_ALIVE: bool | None = None


def _ollama_embed(texts: list[str]) -> list[list[float]] | None:
    """调用本地 Ollama embedding (无需 API key, 数据不出本机)。

    自动读取 LLM 配置中的 OLLAMA_BASE_URL (默认 http://localhost:11434),
    模型可用 EMBEDDING_MODEL / OLLAMA_MODEL 指定 (默认 nomic-embed-text)。
    失败 (Ollama 未启动/无模型) -> 返回 None 由本地嵌入兑底。
    """
    global _OLLAMA_ALIVE
    if _OLLAMA_ALIVE is False:
        return None
    try:
        from reserve.llm import load_config
        cfg = load_config()
        base = (cfg.get("ollama_base_url") or "http://localhost:11434").rstrip("/")
        model = os.environ.get("EMBEDDING_MODEL", "").strip() or cfg.get("ollama_model", "nomic-embed-text")
    except Exception:
        base = "http://localhost:11434"
        model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
    # 先快速探测 Ollama 是否存活 (2s 超时, 避免每次等待)
    if _OLLAMA_ALIVE is None:
        try:
            req = urllib.request.Request(f"{base}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                _OLLAMA_ALIVE = resp.status == 200
        except Exception:
            _OLLAMA_ALIVE = False
            print(f"[embedding] ollama not reachable at {base}, use local embedding")
            return None
    try:
        out = []
        for t in texts:
            body = json.dumps({"model": model, "prompt": t}).encode("utf-8")
            req = urllib.request.Request(f"{base}/api/embeddings", data=body, headers={
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            emb = data.get("embedding")
            if not emb:
                return None
            out.append([float(x) for x in emb])
        return out
    except Exception as e:
        print(f"[embedding] ollama api error, fallback to local: {e}")
        return None
