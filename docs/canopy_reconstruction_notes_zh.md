# rs_data_5 植物 3D 重建说明

## 使用的数据

当前已经生成并验证过的结果来自这个数据文件夹：

```text
rs_data_5/test_plant_20230809132457
```

`rs_data_5` 目录下目前能看到 6 个 `test_plant_*` 原始扫描文件夹。每个文件夹可以看作一组植物 RGB-D 扫描数据，里面主要包含：

```text
rgb_<timestamp>.png
depth_<timestamp>.png
kdc_intrinsics.txt
kd_intrinsics.txt
```

程序既可以处理单个植物文件夹，也可以直接处理整个 `rs_data_5` 目录。

## 原来的重建为什么效果不好

原来的方法主要依赖普通 RGB-D 点云拼接和 ICP 配准。ICP 适合处理连续帧之间有明显共同 3D 结构、并且目标比较稳定的场景。

但是 `rs_data_5` 这组数据更像是一个俯视角滑轨扫描：植物会从画面中经过，同时画面里还有轨道、地面、盒子、色卡、小盆栽等背景物体。如果直接把整张深度图都转成点云再做 ICP，算法很容易对齐背景，而不是对齐目标植物，所以最后植物点云会散掉，形状不成形。

因此现在的实现不再把它当作普通全场景 ICP 问题，而是使用更适合植物俯视扫描的 canopy reconstruction 方法。

## 算法原理

### 1. 读取 RGB-D 数据

程序读取一个 record 文件夹里的所有 `rgb_*.png` 和 `depth_*.png`，并读取 RealSense 相机内参文件：

```text
kdc_intrinsics.txt
kd_intrinsics.txt
```

相机内参后面会用于把 2D 像素和 depth 转换成 3D 坐标。

### 2. 自动分割植物叶片

如果数据里没有人工 mask，程序会自动从 RGB 图像中找绿色叶片区域。

它会把 RGB 图像转换到 HSV 颜色空间，同时计算 excess green：

```text
ExG = 2 * G - R - B
```

只有同时满足绿色色相、饱和度、亮度和 ExG 阈值的像素才会被保留。然后程序会去掉小连通区域，避免色卡、噪声、背景小绿块、小盆栽等干扰目标植物。

### 3. 选择目标植物帧

每一帧的植物 mask 会被打分，主要依据是：

```text
mask 面积
是否贴近图像边缘
mask 是否足够连续
```

得分最高的一帧会被选为 reference frame，也就是参考帧。然后程序选取参考帧附近质量较好的若干帧进行融合。

### 4. 根据植物运动对齐图像

普通 ICP 会受背景影响，所以这里不使用背景做配准。

程序计算每张植物 mask 的中心点，然后根据这些中心点估计植物在图像平面上的移动。因为这组数据近似是滑轨扫描，所以主要运动可以用 2D 平移来描述。

之后，每一帧都会被平移到参考帧的位置，使多张植物图像对齐。

### 5. 融合深度图

对齐后的 depth map 会被融合到一个更大的 canvas 上。使用更大的 canvas 是为了避免平移后植物边缘被原始图像边界裁掉。

在植物 mask 内部，程序会：

```text
过滤异常 depth
填补无效 depth 区域
对 depth 做平滑
融合多帧 depth
```

这样可以得到更连续的植物 canopy 深度图。

### 6. 从 fused depth 生成 3D 点云和网格

程序使用相机内参把每一个有效像素转换成 3D 点：

```text
X = (u - cx) * Z / fx
Y = (v - cy) * Z / fy
Z = depth
```

其中：

```text
u, v 是像素坐标
Z 是深度值
fx, fy, cx, cy 来自相机内参
```

然后程序根据 fused depth 生成：

```text
canopy_points.ply
canopy_mesh.ply
```

`canopy_points.ply` 是彩色点云，`canopy_mesh.ply` 是带颜色的三角网格。

### 7. 生成可拖动查看的 3D 网页

为了方便查看结果，程序还会生成：

```text
canopy_viewer.html
```

这个 HTML 文件内嵌了下采样后的点云数据和 WebGL 查看器。打开后可以：

```text
鼠标拖动旋转
滚轮缩放
双击复位
```

不需要额外安装 MeshLab 或 CloudCompare 也可以快速检查 3D 效果。

## 运行方法

处理整个 `rs_data_5`：

```bash
python main.py --input rs_data_5 --max-frames 11 --coverage-threshold 1
```

只处理一个植物文件夹：

```bash
python main.py --input rs_data_5/test_plant_20230809132457 --max-frames 11 --coverage-threshold 1
```

现在默认模式已经是 `canopy`，所以不写 `--mode canopy` 也可以。

## 输出文件

每个植物 record 的输出会写到：

```text
rs_data_5/canopy_batch/<record_name>/
```

主要输出包括：

```text
canopy_points.ply       彩色点云
canopy_mesh.ply         彩色三角网格
canopy_viewer.html      可拖动旋转的浏览器 3D 查看器
fused_rgb_masked.png    对齐融合后的植物俯视图
fused_mask.png          最终植物 mask
fused_depth_vis.png     深度/高度可视化图
canopy_summary.json     重建参数、选帧信息、输出路径和点数统计
auto_masks/             自动生成的植物 mask
```

## 代码对应关系

### 主程序入口

```text
main.py
```

对应功能：

```text
_discover_records    判断输入是单个植物文件夹还是 rs_data_5 根目录
build_parser         定义命令行参数
main                 调用 canopy 重建，并输出结果路径
```

### 核心重建算法

```text
processing/canopy.py
```

对应功能：

```text
CanopyReconstructionConfig      canopy 重建参数
_auto_leaf_mask                 自动绿色叶片分割
_load_auto_candidates           生成并筛选自动 mask
_select_frames                  选择参考帧和用于融合的帧
_estimate_alignment_transforms  根据植物 mask 中心估计图像平移
_build_canvas_transforms        创建扩大后的融合 canvas
_fill_depth_inside_mask         depth 过滤、补洞和平滑
_build_mesh_and_point_cloud     fused depth 转换成点云和 mesh
reconstruct_canopy              完整 canopy 重建流程
```

### 交互式 3D 查看器

```text
visualiser/viewer.py
```

对应功能：

```text
write_point_cloud_viewer    把点云写成 canopy_viewer.html
_viewer_html                WebGL 拖动旋转和缩放逻辑
```

### 测试

```text
tests/test_e2e.py
```

对应功能：

```text
测试普通 RGB-D 重建仍然可用
测试 mask-guided canopy 重建
测试自动 mask canopy 重建
测试 canopy_viewer.html 是否生成
```

## 验证方法

端到端测试命令：

```bash
python -m unittest tests.test_e2e -v
```

当前这个测试已经通过。

如果要运行完整 `pytest`，需要先确保 `requirements.txt` 中的依赖都已经安装，包括 `Pygments`。

## 总结

这套方法的关键点是：不再对整张图的背景做 ICP，而是先分割目标植物，再根据植物本身的运动进行对齐，最后融合 depth 生成 3D canopy。

这样更适合 `rs_data_5` 这种俯视滑轨扫描数据，也能避免背景、盒子、轨道和色卡把重建结果带偏。
