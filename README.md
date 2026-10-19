# YGO Tactical Assistant

按照 [指导 v0.1](docs/指导v0.1.md) 实现的 Windows Master Duel 视觉工作台。当前完成 Phase 0 + Phase 1：窗口选择、实时画面、ROI 框选校准、录像输入和共用帧管线。

## 直接打开

当前机器已配置 `.venv`，双击 **`start.cmd`**，或在项目目录执行：

```powershell
.\.venv\Scripts\python.exe run.py
```

1. 在顶部选择 `masterduel`，点击「开始实时采集」。默认直接捕捉游戏窗口，可被助手或 IDE 遮挡，也可留在后台，无需缩小游戏或并排摆放。
2. 在游戏中打开右侧决斗日志；效果描述会在对应效果出现时显示。
3. 右侧选择「决斗日志」或「效果描述」，点击「框选 / 重画选中区域」，在主画面拖出矩形。框内拖动可移动，右下角方块可缩放。
4. 检查右侧两个裁剪预览，点击「保存 ROI」。默认保存到 `configs/regions.yaml`；「另存为」可保存不同布局。
5. 点击「导入录像」，播放、暂停、逐帧或拖动时间轴。**输入源切换保留同一套 ROI**，坐标按原始画面比例缩放。
6. 「保存当前帧及 ROI」会输出原始 PNG、两个 ROI PNG 和含来源/帧 ID/时间戳/配置的 `metadata.json`，位置在 `data/captures/`。

快捷键：空格播放/暂停录像，左右方向键逐帧，Ctrl+S 保存 ROI。停止采集后保留冻结画面；输入源失败时显示原因，可重新选择后启动。

**默认使用 WGC 原生窗口捕捉，原始帧不缩放。** 本机 MD 的原生客户区为 2048×1152，完整保留这些像素，仅剔除标题栏和边框。助手预览可缩放，PNG 和 ROI 均从原始帧生成。窗口原生像素取决于游戏实际渲染的客户区尺寸，无法凭捕捉把低分辨率画面变为更高细节。

本机实测 MD 最小化后停止向系统输出帧，助手保持会话并等待，窗口还原后自动恢复；不会用冻结画面伪造新帧。**后台或被遮挡与最小化是不同情况**，日常可将游戏放在后台，保持原生大小。

`configs/app.yaml` 的 `capture_backend: wgc` 为默认；只有主动改为 `dxcam` 才使用旧的屏幕可见区域采集，后者仍受遮挡及跨屏限制，不会自动回退污染素材。更改游戏内部 UI 缩放、宽高比或导入带黑边的录像时应重新校准 ROI。

## 环境与安装

支持 Python 3.11 / 3.12；本机已验证 Windows x64 + Python 3.12.14。原设计首选 3.11，现将经过实测的 3.12 加入包支持范围；3.11 尚未单独实测。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e ".[dev]"
.\.venv\Scripts\python.exe run.py --check
.\.venv\Scripts\python.exe -m pytest -q
```

`requirements.lock` 固定本机 Windows 环境的运行、测试及传递依赖；构建工具固定在 `pyproject.toml`。`requirements.test-py312.txt` 是最初 Phase 0 的历史环境记录，当前以 `requirements.lock` 为准。

```powershell
# 可选的启动方式
.\.venv\Scripts\python.exe run.py --window-title masterduel
.\.venv\Scripts\python.exe run.py --video data/captures/md_log_open/md_probe.mp4
```

`run.py` 自动加载项目配置，双击启动不依赖当前目录。配置内相对路径以配置文件目录为基准。采集频率、预览频率、队列容量、ROI 路径及截图目录均可修改 `configs/app.yaml`。

## 架构和验证

实时 WGC（或显式选择的 DXcam）与 OpenCV 视频读取输出相同的 `Frame`（uint8 BGR、源内帧 ID、毫秒时间戳），由同一个后台 `FramePipeline` 提供给界面。WGC 使用系统回调与单帧槽，复制拥有独立内存的原始客户区像素，记录原始系统时间戳；帧队列有界，界面定时取最新帧，避免 Qt 事件队列堆积。ROI 裁剪只依赖 `Frame` 和 `RegionProfile`。录像跳转使用视频帧索引，时间显示优先使用解码时间戳。

事件与状态契约保持版本化，未知信息使用 null。当前实现尚不包含 OCR、事件推演、规则引擎、Combo 或模型。

已通过 33 项自动测试和真实 MD 的原生窗口、遮挡、最小化等待及自动恢复验证；见 [原生窗口捕捉验收](docs/WINDOW_CAPTURE.md)、[Phase 0/1 历史验收](docs/PHASE_0_1_VERIFICATION.md) 与 [开发计划](docs/DEVELOPMENT_PLAN.md)。真实素材和验证截图留在本地 `data/captures/`，不纳入 Git。

## 调试工具

```powershell
# 列出可见窗口
.\.venv\Scripts\python.exe -X utf8 tools/inspect_capture.py --list
# 采集真实 MD、保存原始帧/ROI，并录制短片验证同一配置的录像读取
.\.venv\Scripts\python.exe -X utf8 tools/inspect_capture.py --title masterduel --seconds 5
# 短暂显示生成的测试窗口，验证 WGC 客户区尺寸、颜色、重开和桌面工作台
.\.venv\Scripts\python.exe tools/smoke_desktop.py
# 用纯色窗口完全遮挡真实 MD，再短暂最小化/还原，验证原生采集
.\.venv\Scripts\python.exe tools/verify_wgc_window.py
```

`tools/verify_md_workbench.py` 用已打开的 MD 回放验证实时 → 鼠标框选 → 保存重载 → 录像导入 → 逐帧，并保存截图与 JSON 报告。它会写入 ROI 配置；`--layout` 还会临时调整游戏窗口，需 2560 像素以上桌面。普通使用不需要运行此工具。
