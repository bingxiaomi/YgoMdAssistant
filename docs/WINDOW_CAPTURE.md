# 原生窗口捕捉与训练图像质量

2026-10-19，Windows x64 / Python 3.12.14。默认后端为 Windows Graphics Capture，依赖 `windows-capture==2.0.1`，通过所选窗口的 HWND 创建捕捉会话。

## 实际行为

- 直接获取所选窗口表面，支持游戏在后台或被其他窗口遮挡；不再依赖屏幕上所选矩形当前显示什么。
- 本机 MD 返回的完整窗口帧为 **2050×1184 BGRA**；与 DWM 的扩展窗口边界一致。按物理客户区位置剔除左侧 1 像素、上方 31 像素等窗口装饰，得到 **2048×1152 BGR**。没有插值、缩小或放大。
- 仅预览绘制会缩放。ROI、PNG 和后续识别输入均来自完整原始帧；源帧尺寸始终显示在界面底部。
- 截图元数据增加 `capture_backend` 与 `source_timestamp_100ns`，保留 WGC 系统帧时间戳；`timestamp_ms` 为相对此会话首帧的毫秒数。
- 原生帧回调只保留一张待消费图像，复制独立缓冲区后才交给处理管线；不会保留失效的原生帧视图。
- 没有新帧时返回等待状态，不重用最后一张画面生成新编号/时间戳。错误时停止，不自动回退到 DXcam。

WGC 捕捉的是游戏实际窗口表面。原生窗口为 2048×1152，就保留该尺寸；若游戏本身以较低尺寸渲染，捕捉不能补回不存在的细节。PNG 保存路径无损；调试 MP4 用于验证录像流程，有损编码片段不能作为原始像素质量的依据。

## 遮挡实测

`tools/verify_wgc_window.py` 创建纯洋红色窗口，完全覆盖真实 MD 客户区，同时比较 DXcam 屏幕采集与 WGC HWND 采集：

| 检查 | 实测结果 |
| --- | --- |
| 实际遮挡覆盖率（桌面截图） | 100% 洋红色 |
| WGC 图像洋红色比例 | 0% |
| WGC 输出尺寸 | 2048×1152，保持原生客户区大小 |
| 遮挡期间新帧 | 收到 21 张用于验证的原生新帧 |
| 源时间戳 | 单调递增 |
| 最小化时 | 会话保持，停止向管线交付训练帧 |
| 还原后 | 自动恢复新帧，尺寸仍为 2048×1152 |

证据保存在 `data/captures/wgc_verification/report.json`、`desktop_occluded/` 与 `native_covered/`。两个目录均含原始 PNG、ROI PNG 和元数据。没有修改游戏分辨率或执行对局动作。

桌面工作台也在默认 WGC 下重新通过实时 → 鼠标框选 → 保存重载 → 录像共用 → 逐帧验证，且全程保持游戏原生 2048×1152，没有并排缩小窗口。报告与截图在 `data/captures/md_workbench/`，其中 `report.json` 明确记录 `capture_backend: wgc`。

## 最小化边界

独立探针绕过适配层，直接统计底层 WGC 回调：普通状态和还原后能持续收到不同画面；MD 最小化后，等待过渡期再观察两秒，没有新回调。本机不具备持续最小化取新帧的条件。

因此支持策略为：**后台/被遮挡正常采集，最小化等待，还原自动继续**。最小化过程中不保存缓存帧；界面保留的最后一张预览有其真实旧时间戳，并显示最小化等待状态。还原瞬间客户区可能暂时为空，或新帧尺寸尚未与窗口几何同步；这些属于可恢复的过渡状态，丢弃不匹配帧并等待下一张，不缩放凑尺寸，也不终止会话。

可用性随游戏和系统行为变化；不通过游戏进程注入、修改渲染逻辑或虚构图像来填补最小化后的空缺。

## 验证与配置

- 33 项 pytest 测试通过，新增覆盖原生像素精确裁剪、尺寸变化、独立帧内存、无帧不重复、最小化等待、还原过渡及恢复。
- `tools/smoke_desktop.py` 默认验证 WGC；生成窗口的颜色、客户区尺寸、录像预览，以及同一 HWND 在新线程重开均通过。证据在 `data/captures/desktop_smoke_wgc/`。
- `configs/app.yaml` 使用 `capture_backend: wgc`。若显式设为 `dxcam`，采用旧屏幕采集，并显示其受遮挡限制的说明。
- UI 和视频继续共用 `Frame`、`FramePipeline` 和 `RegionProfile`，已有 ROI 无需因更换后端迁移。

接口依据：[windows-capture Python 源码](https://github.com/NiiightmareXD/windows-capture/blob/main/windows-capture-python/windows_capture/__init__.py)（HWND、帧缓冲区与系统时间戳）；[Microsoft DWM 窗口边界定义](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)。当前适配器以安装后的 2.0.1 代码及上述本机实测为准。
