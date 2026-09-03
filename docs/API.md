# Astrometry Service API

本地化星空图解算服务的 HTTP 接口。上传一张图片，返回天球坐标。

> **服务地址**：`http://117.72.38.57:8010`
>
> 服务器本机调用可用 `http://localhost:8010`。
> 从其他机器调用，用公网 IP `http://117.72.38.57:8010`。

---

## 目录

- [端点列表](#端点列表)
- [POST /solve](#post-solve)
- [GET /analyse](#get-analyse)
- [GET /health](#get-health)
- [HTTP 状态码](#http-状态码)
- [调用示例](#调用示例)
- [关键约束](#关键约束)

---

## 端点列表

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/solve` | 解算图片，返回 RA/Dec/WCS |
| `POST` | `/analyse` | 提取 EXIF 信息（焦距/视场估算），不实际解算 |
| `GET`  | `/health` | 健康检查 |

所有请求/响应均为 JSON 格式，**图片通过 `multipart/form-data` 上传**。

---

## POST /solve

对一张图片做 plate-solving，返回天球坐标。

### 请求

**Content-Type**: `multipart/form-data`

| 字段 | 必填 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `image` | ✅ | file | — | JPEG / PNG / FITS 图片 |
| `scale_low` | ❌ | float | — | 视场下限（单位见 `scale_units`）|
| `scale_high` | ❌ | float | — | 视场上限 |
| `scale_units` | ❌ | string | `arcminwidth` | `arcminwidth` / `degwidth` / `focalmm` / `arcsecperpix` |
| `downsample_factor` | ❌ | int | `4` | 降采样倍数（越大越快但精度越低）|
| `depth_low` | ❌ | int | `50` | 最小 quad 数 |
| `depth_high` | ❌ | int | `100` | 最大 quad 数 |
| `ra` | ❌ | float | — | 搜索中心 RA（度），hint |
| `dec` | ❌ | float | — | 搜索中心 Dec（度），hint |
| `radius` | ❌ | float | — | 搜索半径（度）|

**最重要的调用**：**只传 `image`，什么都不传也能解**。
服务端会读 EXIF，自动判断走哪条路。

**判断逻辑**（不是“有没有 EXIF”，是“有无有效焦距”）：

| EXIF 状态 | 走的策略 | 典型耗时 |
|---|---|---|
| 有 `FocalLength` 或 `FocalLengthIn35mmFilm` > 0 | 焦距模式（1 次 solve）| 15-20s |
| 有 EXIF 但**焦距为空**（如小米某些图）| race 3 段 | 7-30s |
| 无 EXIF / EXIF 被剥 | race 3 段（若宽图则 race + crop）| 7-30s |

### 响应（成功）

**HTTP 200**：

```json
{
  "solved": true,
  "ra": 92.929520,
  "dec": -2.809374,
  "pixel_scale": 23.899,
  "field_width": 39.94,
  "field_height": 26.66,
  "rotation": -90.0,
  "wcs_header": {
    "CRVAL1": "92.929520",
    "CRVAL2": "-2.809374",
    "CRPIX1": "3008",
    "CRPIX2": "2008",
    "CTYPE1": "RA---TAN-SIP",
    "CTYPE2": "DEC--TAN-SIP",
    "...": "完整 FITS WCS 头（共 51 个字段）"
  },
  "solve_time": 16.08,
  "raw_output": "Reading input file ...\nSolving...\nField 1 solved: ...\n"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `solved` | bool | **true=解出来了** |
| `ra` | float | 赤经（度，J2000）|
| `dec` | float | 赤纬（度，J2000）|
| `pixel_scale` | float | 像素比例（**单位始终是 arcsec/pix**）|
| `field_width` | float | 视场宽（**单位始终是 deg**）|
| `field_height` | float | 视场高（**单位始终是 deg**）|
| `rotation` | float | 旋转角（度）|
| `wcs_header` | object | 完整 FITS WCS 头（51 个字段，含 CRVAL/CRPIX/CTYPE/CD/SIP 系数等）|
| `solve_time` | float | 实际解算耗时（秒）|
| `raw_output` | string | solve-field 完整日志（debug 用，业务可忽略）|

**WCS 转换**：如果需要把图像像素 (x, y) → 天球坐标 (RA, Dec)，
用 `wcs_header` 喂给 `astropy.wcs.WCS()` 或 `astLib.astWCS.WCS()`。

### 响应（未解出）

**HTTP 200**（**注意：未解出也返回 200，看 `solved` 字段**）：

```json
{
  "solved": false,
  "solve_time": 55.82,
  "raw_output": "Field 1 did not solve ...\n"
}
```

**业务上判断成功**：检查 `response.json()["solved"] == true`，**不要只看 HTTP 状态码**。

`raw_output` 是 solve-field 的原始 stdout/stderr（astrometry.net C 工具的日志）。
**总是返回**，约 1500-1600 字符，含解算进度：`simplexy: found N sources`、log-odds ratio、索引命中、Field center 等。

`raw_output` **不是用户友好错误消息**——是英文技术日志，适合排障但不适合直接给终端用户。
业务处理时**只看 `solved` 字段**，`raw_output` 可忽略或写日志备查。

### 响应（超时 / 服务端错误）

| HTTP | 含义 | 常见原因 |
|---|---|---|
| `400` | Bad Request | 解析 multipart 失败（**最常见：文件太大**，公网 > 4MB）|
| `413` | Payload Too Large | 文件超大（公网不该出现这个）|
| `500` | Internal Server Error | solve-field 崩溃、磁盘满、索引损坏 |
| `503` | Service Unavailable | 服务未启动 |
| `504` | Gateway Timeout | 上游代理超时（公网可能遇到）|

### 默认参数详解

| 参数 | 默认值 | 何时应该调大/调小 |
|---|---|---|
| `downsample_factor` | `4` | 视场太小（< 2°）+ 无解 → 改 `2` 提高精度 |
| `depth_low/high` | `50/100` | 城市光污染严重 + 无解 → 改 `100/200` |
| `scale_units` | `arcminwidth` | 标准单位，不要用 `arcsecperpix`（容易算错 60 倍）|

---

## GET /analyse

提取图片 EXIF 信息，估算视场范围（**不实际解算**）。

### 请求

**Content-Type**: `multipart/form-data`

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `image` | ✅ | file | JPEG / PNG / FITS 图片 |

### 响应（成功）

**HTTP 200**：

```json
{
  "success": true,
  "has_exif": true,
  "make": "NIKON CORPORATION",
  "model": "NIKON D610",
  "focal_length": 50,
  "sensor_name": "Full Frame (35mm)",
  "detected_from": "exif",
  "fov": {
    "width_degrees": 39.60,
    "height_degrees": 26.99,
    "width_arcmin": 2375.87,
    "height_arcmin": 1619.49,
    "diagonal_degrees": 46.79
  },
  "scale_low": 1979.89,
  "scale_high": 2851.04,
  "scale_units": "arcminwidth"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | bool | 是否成功提取信息 |
| `has_exif` | bool | 图片是否含 EXIF |
| `make` | string | 相机厂商（EXIF） |
| `model` | string | 相机型号（EXIF） |
| `focal_length` | float | 焦距（mm，35mm 等效）|
| `sensor_name` | string | 传感器类型（如 `Full Frame (35mm)`、`APS-C`）|
| `detected_from` | string | 信息来源（`exif` / `image_only`）|
| `fov.width_degrees` | float | 视场宽（度）|
| `fov.height_degrees` | float | 视场高（度）|
| `fov.width_arcmin` | float | 视场宽（角分）|
| `fov.height_arcmin` | float | 视场高（角分）|
| `fov.diagonal_degrees` | float | 对角视场（度）|
| `scale_low` | float | 推荐给 `/solve` 的 arcminwidth 下限 |
| `scale_high` | float | 推荐给 `/solve` 的 arcminwidth 上限 |
| `scale_units` | string | `scale_low/high` 的单位（始终是 `arcminwidth`）|

**用途**：
- 上传前先用 `/analyse` 看 EXIF，决定要不要传给 `/solve` 哪些 scale 参数
- 如果直接调 `/solve` 不传参数，服务端会**自己调** `/analyse` 内部逻辑，效果相同

---

## GET /health

健康检查。

### 响应

**HTTP 200**：

```json
{
  "status": "healthy",
  "uptime_seconds": 3600.5,
  "version": "0.1.0"
}
```

---

## HTTP 状态码

| 状态码 | 含义 |
|---|---|
| `200` | 请求成功（包括 `solved: false` 也用 200）|
| `400` | 客户端错误（multipart 解析失败，**最常见：文件太大**）|
| `500` | 服务端错误（solve-field 失败、磁盘满等）|
| `503` | 服务未启动 |

---

## 调用示例

### curl（最简单）

```bash
# 只传图片（推荐）
curl -X POST -F "image=@photo.jpg" \
  http://117.72.38.57:8010/solve

# 手动指定焦距（已知焦距）
curl -X POST \
  -F "image=@photo.jpg" \
  -F "scale_low=45" -F "scale_high=55" -F "scale_units=focalmm" \
  -F "downsample_factor=4" -F "depth_low=50" -F "depth_high=100" \
  http://117.72.38.57:8010/solve
```

### Python（生产推荐）

```python
import requests

# 只传图片
r = requests.post(
    'http://117.72.38.57:8010/solve',
    files={'image': open('photo.jpg', 'rb')},
    timeout=60,  # 服务端硬超时 60 秒
)
data = r.json()

if data.get('solved'):
    print(f"RA = {data['ra']:.4f}°")
    print(f"Dec = {data['dec']:.4f}°")
    print(f"FOV = {data['field_width']:.2f}° × {data['field_height']:.2f}°")
else:
    print(f"未解出（耗时 {data.get('solve_time', 0):.1f}s）")
```

### JavaScript（fetch）

```javascript
const form = new FormData();
form.append('image', fileInput.files[0]);

const resp = await fetch('http://117.72.38.57:8010/solve', {
  method: 'POST',
  body: form,
});

const data = await resp.json();
if (data.solved) {
  console.log(`RA = ${data.ra}°, Dec = ${data.dec}°`);
}
```

### Go

```go
import (
    "bytes"
    "mime/multipart"
    "net/http"
    "os"
)

func solve(path string) (*Result, error) {
    file, _ := os.Open(path)
    defer file.Close()

    body := &bytes.Buffer{}
    writer := multipart.NewWriter(body)
    part, _ := writer.CreateFormFile("image", file.Name())
    part.ReadFrom(file)
    writer.Close()

    resp, err := http.Post(
        "http://117.72.38.57:8010/solve",
        writer.FormDataContentType(),
        body,
    )
    defer resp.Body.Close()
    // ...
}
```

---

## 关键约束

### 1. 公网上传文件大小 ≤ 4MB

| 场景 | 限制 | 失败表现 |
|---|---|---|
| 服务器本机 | 几乎无限制 | — |
| 公网 `117.72.38.57:8010` | **≤ 4MB 成功，≥ 5MB 失败** | HTTP 400 "Failed to parse form" |

**根因**：服务器上行带宽 ~530KB/s × 服务商 10s timeout ≈ 5MB 临界。
**不是服务端设计问题**，是网络层问题。

**客户端解决办法**：

```python
from PIL import Image
import piexif

img = Image.open('big.jpg')  # 11MB
exif = piexif.load(img.info.get('exif', b''))  # ⚠️ 必须先读 EXIF
img.save('small.jpg', 'JPEG', quality=90, exif=piexif.dump(exif))
# → 3MB，EXIF 完整保留，像素无损
```

| JPEG quality | 文件大小（11MB →）| EXIF | 解算速度 |
|---|---|---|---|
| q100 | 11MB（不重压）| ✅ | ❌ 公网上传 400 |
| q90 | 3.0MB | ✅（用 piexif）| ✅ |
| q85 | 2.3MB | ✅ | ✅ |
| q80 | 1.8MB | ✅ | ✅ |
| q70 | 1.3MB | ✅ | ✅ |

**注意**：JPEG 重压（q90）**不是 resize**——像素完全不动，只丢文件体积。
**resize 会丢 ~81% 星点**，导致解算变慢 + 成功率下降。

### 2. 服务端硬超时 60 秒

超过 60 秒服务端会自动 cancel，进程组一起 SIGKILL。
客户端 `requests.post(..., timeout=60)`（或更长）即可。

### 3. 业务判断标准

- ✅ **成功**：`response.status_code == 200` && `response.json()["solved"] == true`
- ❌ **失败**：其他情况（包括 HTTP 400/500）

### 4. 不需要传任何 scale 参数

服务端**默认会读 EXIF + 看图宽，自动选策略**。
下游服务**只传图片**就够了——不要为了让"看起来更稳"而乱传 scale 参数，反而会绕过智能决策。

### 5. 并发安全

- 单个客户端**多次同时**调 `/solve` 完全安全（每次请求独立 tempDir）
- race 模式**内部**就 3-4 并发，所以一个 race 请求占用 ≈ 4 个普通请求资源
- 不建议单客户端同时发超过 16 个请求

---

## 故障对照表

| 现象 | 原因 | 解决 |
|---|---|---|
| HTTP 400 "Failed to parse form" | 公网文件 > 4MB | 客户端 JPEG 重压到 q90 |
| HTTP 504 / 请求 hang 60 秒 | 网络太慢或服务端超时 | 检查文件大小 + 服务状态 |
| `solved: false` | 视场超出 70° 或星点太少 | 手动指定 scale + 检查图片 |
| `solved: false` 但 `solve_time = 60.0` | 智能决策跑了 3 段 race 都超时 | 加 `--focal-mm` 显式缩窄（用脚本）或客户端调 `/analyse` 后传 scale |
| 一直 `Connection refused` | 服务没启 | `docker ps` 检查容器 |
