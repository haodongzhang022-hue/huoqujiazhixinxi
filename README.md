# CNB完整示例

![badge](/-/badge/git/latest/ci/pipeline-as-code)
![badge](/-/badge/git/latest/ci/status/auto_merge)

> 📌 **本项目实际能力（huoqujiazhixinxi 获取价值信息）**
>
> - 🌐 **全球金融数据超索引框架**（Issue #6 专项）：六维分类（数据类别×国家×交易所×时间级别×品种×交易类型）→ 筛选器 → 数据源脚本索引 → 渐进披露 → 触发/定时获取
>   - 文档：**[docs/finance-framework.md](docs/finance-framework.md)**、**[docs/finance-lance.md](docs/finance-lance.md)**
>   - 快速体验：`python3 -m finance.cli search --data-class futures --region CN`、`python3 -m finance.cli fetch --instrument CRYPTO.BTC --source ccxt`、`python3 -m finance.api --port 8100`
>   - 🗄️ **LanceDB 统一数据管理**（Issue #6 二期）：渠道/列定义/参数/任务/数据/日志/挖掘候选 七表统一入库，爬虫解耦为「通用模板 + 分渠道定义」；`python3 -m finance.cli lance init` / `lance fetch` / `lance tasks` / `lance discovery`
> - 📦 **开源项目信息获取与筛选管道**：GitHub 每日新热项目采集 → 归一化 → 三分类 → LanceDB 储备库 → 条件触发 → 质量评估 → Web 管理台
>   - 文档：**[docs/pipeline.md](docs/pipeline.md)**
>
> 测试：`python3 tests/test_finance.py`（金融框架 8 项）+ `python3 tests/test_reserve.py`（储备库 34 项）

## NPC

1. [Claude Code](https://cnb.cool/npc/claude-code)
2. [Open Code](https://cnb.cool/npc/open-code)
3. [HOK - 王者荣耀英雄氛围编程助手](https://cnb.cool/npc/hok)
4. [Chart - 数据可视化图表生成助手](https://cnb.cool/npc/chart)
5. [Office - 办公文档处理助手](https://cnb.cool/npc/office)
6. [Image - AI 图片生成与处理助手](https://cnb.cool/npc/image)
7. [TTS - 文本转语音合成助手](https://cnb.cool/npc/tts)
8. [Create NPC - 用 NPC 创建 NPC](https://cnb.cool/npc/create-npc)
9. [探索更多 NPC（每周热门）](https://cnb.cool/explore?time=weekly)
10. [NPC Playground - 从零开始创建你的 NPC](https://cnb.cool/npc/npc-playground)

## 编程语言

下方示例大部分包含构建环境和开发环境配置：

1. [springboot gradle 构建镜像推送到 CNB 制品库](https://cnb.cool/examples/ecosystem/springboot-gradle-docker)
1. [springboot maven 构建镜像推送到 CNB 制品库](https://cnb.cool/examples/ecosystem/springboot-maven-docker)
1. [springboot maven 构建 jar 包 SSH 部署到服务器](https://cnb.cool/examples/ecosystem/springboot-maven-ssh)
2. [springboot maven 构建镜像推送到 CNB 制品库并使用 JumpServer 部署到内网机器](https://cnb.cool/examples/ecosystem/springboot-maven-docker-jumpserver)
1. [vue 构建静态资源上传到腾讯云 cos](https://cnb.cool/examples/ecosystem/vue-cos-demo)
1. [react 构建将静态资源上传到腾讯云 cos](https://cnb.cool/examples/ecosystem/react-cos-demo)
1. [react 构建将静态资源 SSH 部署到目标服务器](https://cnb.cool/examples/ecosystem/react-ssh-demo)
1. [nextjs 构建全栈应用镜像并推送到 CNB 制品库](https://cnb.cool/arsrna/next-cnb-demo)
1. [react 构建镜像推送到 CNB 制品库，并通过 Docker 部署到 CVM](https://cnb.cool/examples/ecosystem/react-docker)
1. [node express 构建镜像推送到 CNB 制品库](https://cnb.cool/examples/ecosystem/node-express-docker)
1. [hexo + rsync 将静态资源部署到目标服务器](https://cnb.cool/examples/ecosystem/hexo-rsync-remote)
1. [go gin 构建镜像推送到 CNB 制品库和 K8S 集群](https://cnb.cool/examples/ecosystem/go-gin-kubernetes)
1. [go 构建镜像推送到 CNB 制品库](https://cnb.cool/examples/ecosystem/golang-build)
1. [go 编译构建依赖私有仓库](https://cnb.cool/liwenqiu/golang/use-private-lib)
1. [windows 平台 go 编译依赖私有 Git 仓库](https://cnb.cool/cnb/feedback/-/issues/1032)
1. [Node 使用 docker compose 连接 MySQL 和 Redis](https://cnb.cool/examples/ecosystem/nodejs-docker-compose)
1. [dotnet 构建镜像推送到 CNB 制品库](https://cnb.cool/devopschina/dotnet-build)
1. [.NET Core 使用 docker compose 连接 MySQL 构建镜像推送到 CNB 制品库](https://cnb.cool/devopschina/cloud-native-run-dotnet)
1. [构建 Android 项目](https://cnb.cool/examples/ecosystem/android-demo)
1. [R语言 构建镜像推送到 CNB 制品库](https://cnb.cool/examples/ecosystem/r-build)
1. [python flask 构建并将构建产物上传 CNB 制品库](https://cnb.cool/examples/ecosystem/python-flask-docker)
1. [python spug 根据 tag 构建容器上传 CNB 制品库 && 腾讯云容器镜像服务](https://cnb.cool/zhiqiangwang/spug)
1. [使用 endstages 和 COS 实现云开发环境中数据库的持久化存储](https://cnb.cool/xiaofei/cloud-dev-data-persistence-with-cos)
1. [go 多架构镜像构建推送至 CNB制品库，生成多平台附件](https://cnb.cool/dadong.cnb/cloud/Gobuild)
1. [conda环境，已配置snakemake以及Rstudio环境（设置bioconda为清华源），配置生物信息学环境](https://cnb.cool/crl-code/bio-env)

## Issue/pr 使用场景

1. [Issue 信息通知到群聊示例](https://cnb.cool/examples/ecosystem/issue-notice)
2. [CR 评审信息通知到企业微信群](https://cnb.cool/examples/ecosystem/code-review-notice)
3. [Issue 模板示例](https://cnb.cool/examples/templates/issue-templates)
4. [在 Pull Request 中对 commit 进行检查](https://cnb.cool/examples/ecosystem/commit-lint)
5. [在 Pull Request 中进行 AI 代码评审](https://cnb.cool/examples/ecosystem/code-review)

### 标签模板

1. [适合中大型项目的标签示例](https://cnb.cool/cnb/feedback/-/labels)
2. [适合小型项目的标签示例](https://cnb.cool/looc/git-cnb/-/labels)

## 任务集（项目协同工具）

1. [任务集模板示例](https://cnb.cool/examples/mission-templates)

## 知识库

1. [交互式知识库的使用](https://cnb.cool/examples/ecosystem/all-good)
1. [wiki.js 知识库数据同步至 CNB](https://cnb.cool/srebro/doc.srebro.cn)

## 云原生构建进阶

1. [YAML 语法进阶](https://cnb.cool/examples/ecosystem/you-dont-konw-cnb-yaml)
1. [配置自定义按钮手动触发构建](https://cnb.cool/examples/ecosystem/custom-button)
1. [API 触发流水线](https://cnb.cool/examples/ecosystem/api-trigger-pipeline)
1. [利用缓存提升构建速度](https://cnb.cool/examples/ecosystem/use-cache)
1. [综合使用include、reference](https://cnb.cool/examples/ecosystem/include-with-reference)
1. [定时任务检查域名证书状态](https://cnb.cool/cnb/e2e/domain-cert-check)
1. [使用子目录中的 Dockerfile 进行 build](https://cnb.cool/examples/ecosystem/docker-build-with-by)
1. [实现定时拉取代码并自动构建 Release 版本](https://cnb.cool/dadong/cloud/nginx-pack)
1. [在插件Dockerfile中声明settings-from](https://cnb.cool/examples/ecosystem/settings-from)

## 云原生开发

不同语言环境配置，可参考上方**编程语言**部分

1. [自定义开发环境示例](https://cnb.cool/examples/ecosystem/custom-vscode)
1. [使用 vsx 安装包安装插件](https://cnb.cool/examples/ecosystem/install-vsx-extension)
1. [前端项目沙箱运行，一键预览](https://cnb.cool/examples/ecosystem/code-sandbox-in-cnb)
1. [🛫 快速拉起一个基础环境(内置go&node)或者好玩的项目(各种开发工具与好玩项目)，直接起飞](https://cnb.cool/znb/qifei)
1. [配置使用中文插件](https://cnb.cool/examples/ecosystem/chinese-env)
1. [🎯 CNB多系统原生开发环境整合](https://cnb.cool/dadong.cnb/cloud/OS)
1. [☁️ CNB一键开启云原生Dify实现数据持久化存储](https://cnb.cool/dadong/cloud/dify-cnbcloud)
1. [🚀 云原生桌面一键体验云冲浪 🌊](https://cnb.cool/set/Playground/Desktop)
1. [🎭 基于云原生构建启动自定义云原生开发环境](https://cnb.cool/znb/start-custom-environment)
1. [云原生开发启动 N8N 服务](https://cnb.cool/examples/ecosystem/n8n-launcher)
1. [云原生开发使用 devcontainer](https://cnb.cool/examples/ecosystem/devcontainer)
1. [自定义 JetBrains IDE 开发环境](https://cnb.cool/examples/ecosystem/jetbrains)

## 云原生开发仅预览模式

仅预览模式目前为 beta 版（暂无公开文档），后续可能会改变用法

1. [使用 CNB 预览模式](https://cnb.cool/examples/ecosystem/only-preview)
1. [jupyter 预览模式](https://cnb.cool/examples/ecosystem/jupyter-preview)
1. [hunyuan 生图预览模式](https://cnb.cool/examples/ecosystem/HunyuanImage-2.1-ComfyUI-Preview-mode)

## 制品上传

### Docker

1. [docker build 并推送到 CNB 制品库](https://cnb.cool/examples/ecosystem/docker-build-and-push)
1. [docker buildx 多架构构建 amd64/arm64 镜像，方案 1(推荐)](https://cnb.cool/examples/ecosystem/docker-buildx-amd-arm-example)
1. [docker buildx 多架构构建 amd64/arm64 镜像，方案 2](https://cnb.cool/examples/ecosystem/multiarch-docker-build-amd-arm)
1. [docker build 并推送到 Docker Hub](https://cnb.cool/cnb/plugins/cnbcool/hello-world)
1. [docker build 并推送到 TCR 容器镜像服务](https://cnb.cool/examples/ecosystem/docker-build-and-push-to-tcr)

### 二进制附件

1. [golang 生成二进制包上传到 CNB release 附件](https://cnb.cool/examples/ecosystem/golang-build)
2. [golang 生成二进制包上传到 CNB commit 附件](https://cnb.cool/examples/ecosystem/golang-build)
3. [golang 生成多平台 (Windows, Linux, Mac) 二进制包上传到 CNB release 附件 - 案例 1](https://cnb.cool/eryajf/glactl)
4. [golang 生成多平台 (Windows, Linux, Mac) 二进制包上传到 CNB release 附件 - 案例 2](https://cnb.cool/zhiqiangwang/tlsctl)


## 部署场景

1. [多环境部署配置(包括审批流)](https://cnb.cool/examples/ecosystem/deploy-config)
1. [ansible 操作 CVM](https://cnb.cool/examples/ecosystem/ansible-demo)
1. [使用 Terraform 进行集群部署作业](https://cnb.cool/examples/ecosystem/terraform-hello-world)
1. [hexo 构建静态资源上传到腾讯云 COS](https://cnb.cool/examples/ecosystem/hexo-cos-demo)
1. [使用插件 更新腾讯云容器服务 TKE 中, Deployment 的业务镜像](https://cnb.cool/examples/ecosystem/deploy-to-tke-demo)
1. [自动化部署 EdgeOne Pages](https://cnb.cool/arsrna/next-cnb-eo-demo)
1. [Helm Charts 部署到 kubernetes](https://cnb.cool/looc/helm-example)
1. [Node Express 部署到 TCB 云托管](https://cnb.cool/examples/ecosystem/cloudbase-run-demo)
1. [Vue 部署到 TCB 静态托管](https://cnb.cool/examples/ecosystem/cloudbase-host-demo)
1. [Node Express 部署到微信云托管](https://cnb.cool/examples/ecosystem/wechat-cloudrun-demo)
1. [腾讯云 CVM 远程命令(无需暴露公网 IP 以及密码)](https://cnb.cool/cnb/plugins/tencentcom/tcloud-cmd)

## AI
1. [使用 AI 在代码变更时自动生成 codewiki 文档](https://cnb.cool/examples/ecosystem/codewiki)
2. [使用 AI 将 GitHub Actions 语法转换为 CNB 语法 文档](https://cnb.cool/examples/ecosystem/action-to-cnb)

## 插件制作

1. [hello world 插件制作](https://cnb.cool/examples/plugins/hello-world)
1. [自制插件市场](https://cnb.cool/examples/ecosystem/plugins-data-source)

## 超大仓库

1. [125GB 的 AOSP 仓库使用读秒克隆、Volumes 缓存、远程开发](https://cnb.cool/aosp/monorepo)

## 配套工具

1. [代码迁移到 CNB](https://cnb.cool/cnb/plugins/cnbcool/code-import)
1. [制品迁移到 CNB](https://cnb.cool/cnb/plugins/cnbcool/artifact-migrate)
1. [CODING Generic 制品迁移至 CNB Release](https://cnb.cool/cnb/plugins/cnbcool/migrate_generic_assert)
1. [CODING 项目协同事项导入](https://cnb.cool/CODING/tool/migrate-collaboration)
1. [CODING 测试管理迁移至TAPD](https://cnb.cool/table-link/public/coding-test-migrator)
1. [从 CNB 同步代码到其他 Git 托管平台](https://cnb.cool/cnb/plugins/tencentcom/git-sync)
1. [Github 工作流迁移到 .cnb.yml 格式](https://cnb.cool/haorwen/action2cnb) / [在线使用](https://action2cnb.haorwen.top/)
1. [提供 CNB 基础开发构建环境镜像，通过构建按钮指定构建，优雅且舒服](https://cnb.cool/znb/images)
1. [配置腾讯云软件源 Maven、Gradle、NPM、Ubuntu、Debian、Alpine、Python、PHP](https://cnb.cool/examples/mirrors/mirrors.cloud.tencent.com)
1. [单测覆盖率上报 node 版](https://cnb.cool/examples/ecosystem/testing-node-demo)
1. [单测覆盖率上报 go 版](https://cnb.cool/examples/ecosystem/testing-go-demo)
