/**
 * 「星空识别」页样图速测数据。
 *
 * 素材来源：`assets/test1.jpg` / `test2.jpg`（两张真实拍摄星图），
 * 由 `scripts/prepare_quick_samples.py` 一次性生成到 `web/public/samples/`：
 *   - 全尺寸 `quick-testN.jpg`：走服务端生产函数
 *     `services.jpeg_recompress.recompress_jpeg_to_target`（quality 阶梯 90→85→80、
 *     target 4MB、保留 EXIF），因此浏览器把它当普通用户上传即可，上游必定可解
 *   - 缩略图 `quick-testN-thumb.jpg`：480px 宽、已按 EXIF 转正，仅供本列表展示
 *
 * 2026-09-14 真实上游（117.72.38.57:8010）实测：两张全部 solved=true，
 * solve_time 分别 19.9s / 13.0s。
 * （曾收录 test4「黄昏彗星」：视场 54°×36° 星点稀疏，上游耗时 51.3s 已贴近
 *   ASTROMETRY_TIMEOUT=60，演示时容易卡在等待态，故从页面展示中移除；
 *   如需恢复，把 assets/test4.jpg 加回脚本 SAMPLES 并重跑即可。）
 * 换图或重压后请重跑该脚本并同步这里的 size / meta。
 */

export interface QuickSample {
  /** 稳定 id，用于 data-testid 与 loading 态标记 */
  id: string
  /** 全尺寸样图路径（≤4MB，保留 EXIF），点击后下载并作为上传文件提交 */
  src: string
  /** 列表缩略图路径 */
  thumb: string
  /** 进入 scan store 的文件名（会出现在 FormData 里，便于日志追溯） */
  fileName: string
  /** 图版编号用的罗马数字 */
  roman: string
  /** 一句话主题 */
  title: string
  /** 视场 / 设备 / 预计耗时 */
  meta: string
  /** 下载体积提示，让测试者知道"点了要等一下" */
  size: string
  /** 预期命中星座，便于测试者判断链路是否正常 */
  expect: string
}

export const QUICK_SAMPLES: readonly QuickSample[] = [
  {
    id: 'test1',
    src: '/samples/quick-test1.jpg',
    thumb: '/samples/quick-test1-thumb.jpg',
    fileName: 'quick-test1.jpg',
    roman: 'Ⅰ',
    title: '冬夜猎户',
    meta: '50mm 长焦 · 视场 40°×27° · 约 20s',
    size: '2.8MB',
    expect: '猎户座 + 中国星官「伐」',
  },
  {
    id: 'test2',
    src: '/samples/quick-test2.jpg',
    thumb: '/samples/quick-test2-thumb.jpg',
    fileName: 'quick-test2.jpg',
    roman: 'Ⅱ',
    title: '夏季大三角',
    meta: '8192px 宽 · 视场 23°×17° · 约 15s',
    size: '3.1MB',
    expect: '天鹰座 / 天琴座 / 天鹅座',
  },
] as const
