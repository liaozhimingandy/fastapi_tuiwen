# fastapi_tuiwen

博客/社区 API 服务(FastAPI + SQLModel + PostgreSQL + Redis)。

## 视频存储方案(与 utils/video_transcoder.py 输出一致)

```
videos/<YYYYMM>/<video_id>/
  original.mp4                 # 原始文件, 转码输入, 不会被覆盖
  play_list.m3u8               # 多码率入口(master playlist)
  cover.jpg                    # 封面(取第 1 秒帧)
  360p/
    index.m3u8                 # 该档清晰度的 playlist
    init.mp4                   # fMP4 初始化段
    segment_00000.m4s          # 媒体分片(fMP4, 非 .ts)
    ...
  480p/
    index.m3u8
    init.mp4
    ...
  720p/
    ...
  1080p/
    ...
```

要点:
- HLS 使用 fMP4 分片(`.m4s`), 播放端需支持(现代浏览器/播放器均支持)
- 不会上采样: 源视频低于最低档时按原生分辨率动态生成一档(如 `180p`)
- 转码在临时目录完成并通过完整性校验后才发布到正式目录, 失败不会污染线上文件
- 播放地址由 `VideoService._build_play_url` 拼装: `<VIDEO_STORAGE_URL_PREFIX>/<YYYYMM>/<video_id>/play_list.m3u8`

## 运行环境要求

- Python 3.14+ / uv
- **PostgreSQL 18+**：主键使用 `uuidv7()` 作为列默认值，PG 18 之前没有该函数；
  新库由应用启动时的 `init_db()` 自动建表，存量库需要执行迁移（自增 bigint 主键 → uuid7 主键）
- Redis（验证码/缓存）、SMTP（本地用 MailDev 的 1025 端口）

## CI/CD

三个工作流各管一件事，互不耦合：

| 工作流 | 触发 | 职责 |
| --- | --- | --- |
| `ci.yml` | PR（main/develop）、main/develop 推送、手动 | 静态检查 → 单元测试 → 集成测试（PG18+Redis+MailDev）→ 镜像构建与启动冒烟 |
| `build-images.yml` | main/develop/stable 分支、`v*` Tag、手动 | 构建并推送镜像到 Docker Hub 与阿里云 ACR（配了才推；都没配则只本地构建） |
| `release.yml` | `v*` Tag、手动 | 校验 VERSION 与 Tag → 全量测试 → 创建 GitHub Release |

### 镜像标签规则

| 来源 | 版本 | 附加标签 |
| --- | --- | --- |
| `main` 推送 | `dev` | 无（不占 `latest`，不附 sha，避免标签堆积） |
| `develop` 推送 | `develop` | 无（同上；与 `dev` 分开，避免互相覆盖） |
| `stable/A.B.x` 分支 | `A.B` | `sha-<7位>`、`A.B`、`A` |
| Tag `vA.B` / `vA.B.C` | `A.B` / `A.B.C` | `sha-<7位>`、`latest`、`A.B`、`A` |
| Tag `vA.Brc1`（预发布） | `A.Brc1` | `sha-<7位>`（不占 `latest`） |

例：`docker pull <owner>/fastapi_tuiwen:0.3.6`、`:latest`、`:0.3`。

### 需要配置的 Secrets / Variables

仓库 Settings → Secrets and variables → Actions。**两个镜像仓库各自独立判断**：配了哪个就推哪个，
两个都没配时只本地构建、不报错。

| 类型 | 名称 | 说明 |
| --- | --- | --- |
| Secret | `DOCKERHUB_USERNAME` | Docker Hub 用户名（不配则跳过 Docker Hub） |
| Secret | `DOCKERHUB_TOKEN` | Docker Hub Access Token |
| Secret | `ALIYUN_REGISTRY` | 例：`registry.cn-hangzhou.aliyuncs.com`（不配则跳过阿里云） |
| Secret | `ALIYUN_USERNAME` | 阿里云 ACR 用户名；未配时回退到 `DOCKER_USERNAME` |
| Secret | `ALIYUN_PASSWORD` | 阿里云 ACR 密码/访问凭证；未配时回退到 `DOCKER_PASSWORD` |
| Variable | `ALIYUN_NAMESPACE` | 阿里云命名空间，默认 `<owner>` |
| Variable | `DOCKER_REPOSITORY` | 覆盖镜像名，默认 `<owner>/fastapi_tuiwen` |
| Variable | `ENABLE_FLOATING_TAGS` | 是否滚动 `A.B` / `A` 浮动标签，默认 `true` |

> 历史沿革：旧工作流用 `DOCKER_USERNAME` / `DOCKER_PASSWORD` 登录**阿里云** ACR。
> 为免迁移，新工作流的阿里云登录优先用 `ALIYUN_*`，取不到时自动回退到这两个旧名字；
> Docker Hub 改用独立的 `DOCKERHUB_*`，两边不会再互相覆盖。


### 发布新版本

```bash
# 1. 改版本号（main.py 的版本号来自此文件，镜像标签、Release 都会校验它）
echo "0.4.0" > VERSION
git commit -am "chore: bump version to 0.4.0"
git push origin main

# 2. 打 Tag 推送，自动触发镜像构建 + GitHub Release
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```

预发布用 `v0.4.0rc1`（此时 `VERSION` 可写基线 `0.4.0`），产物标记 `prerelease` 且不占用 `latest`。

### 本地跑测试

```bash
uv sync                                  # 安装依赖
uv run pytest tests -q                   # 离线单元测试（无需外部依赖，秒级）
uv run pytest test_main.py -q            # 端到端测试（需 PG18 + Redis + MailDev）
uvx ruff check .                         # 静态检查（规则见 pyproject [tool.ruff]）
```
